"""LLM service with OpenAI-compatible API support (Ollama/vLLM/remote providers)."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx
from redis.asyncio import Redis
import structlog

from app.config import settings
from app.dependencies import get_redis
from app.observability.langfuse_client import LangfuseObserver
from app.services.canary_router import in_canary_bucket

logger = structlog.get_logger("docmind.llm")


class LLMService:
    """Chat-completion wrapper supporting Ollama, OpenAI-compatible, and vLLM backends.

    Unlike the previous version that returned ``None`` for local providers,
    this implementation always attempts to call the configured endpoint.
    A rule-only fallback is returned **only** when no base URL is configured
    or the provider is explicitly set to ``"rule"``.
    """

    # Circuit-breaker: after a failure, skip remote calls for this duration.
    _circuit_open_until: float = 0.0
    _CIRCUIT_COOLDOWN_SECONDS: float = 15.0

    def __init__(self):
        self.provider = (settings.llm_provider or "ollama").lower()
        self.base_url = (settings.llm_api_base_url or "").rstrip("/")
        self.model = settings.llm_model_name or "qwen2.5:7b"
        self.api_key = settings.llm_api_key or ""
        self.langfuse = LangfuseObserver()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_rule_only(self) -> bool:
        """Return True when **no** LLM backend is available at all."""
        return self.provider == "rule" or not self.base_url

    async def health(self) -> dict[str, Any]:
        """Best-effort availability check for configured provider."""
        if self.is_rule_only:
            return {"enabled": False, "available": False, "provider": self.provider, "reason": "rule_mode"}

        try:
            target = await self._resolve_runtime_target_async("", "", "healthcheck")
            async with httpx.AsyncClient(timeout=5.0) as client:
                if target["provider"] == "ollama":
                    resp = await client.get(target["base_url"].replace("/v1", "") + "/api/tags")
                    resp.raise_for_status()
                    tags = [item.get("name", "") for item in resp.json().get("models", [])]
                    has_model = any(tag.startswith(str(target["model"]).split(":")[0]) for tag in tags)
                    return {
                        "enabled": True,
                        "available": True,
                        "provider": target["provider"],
                        "model": target["model"],
                        "profile": target["profile"],
                        "model_pulled": has_model,
                    }

                resp = await client.get(str(target["base_url"]) + "/models", headers=self._headers(str(target["api_key"])))
                resp.raise_for_status()
                return {"enabled": True, "available": True, "provider": target["provider"], "model": target["model"], "profile": target["profile"]}
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"enabled": True, "available": False, "provider": self.provider, "model": self.model, "error": str(exc)}

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 700,
        tenant_key: str = "default",
    ) -> str | None:
        """Generate text via the configured LLM backend.

        Returns the generated text, or ``None`` only when:
        - the provider is explicitly ``"rule"`` (no LLM available), or
        - all retry / circuit-breaker attempts are exhausted.
        """
        if self.is_rule_only:
            return None

        # Circuit breaker
        if time.monotonic() < self.__class__._circuit_open_until:
            logger.debug("llm.circuit_open", provider=self.provider)
            return None

        target = await self._resolve_runtime_target_async(system_prompt, user_prompt, tenant_key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        span = self.langfuse.start_generation(
            name="llm.generate",
            model=str(target["model"]),
            provider=str(target["provider"]),
            input_payload=messages,
            metadata={"temperature": temperature, "max_tokens": max_tokens, "stream": False, "profile": target["profile"]},
        )
        started_at = time.perf_counter()

        try:
            output = await self._call_chat_completions(messages, temperature=temperature, max_tokens=max_tokens, target=target)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            span.finish(
                output=output,
                metadata={"duration_ms": duration_ms, "status": "ok", "profile": target["profile"]},
                usage=self._estimate_usage(system_prompt, user_prompt, output or ""),
            )
            self.langfuse.flush()
            return output
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("llm.generate_failed", error=str(exc), provider=target["provider"], model=target["model"], profile=target["profile"])
            self.__class__._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN_SECONDS
            span.fail(error=str(exc), metadata={"status": "error", "profile": target["profile"]})
            self.langfuse.flush()
            return None

    async def generate_stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Stream tokens from the LLM backend."""
        if self.is_rule_only:
            return

        target = await self._resolve_runtime_target_async(system_prompt, user_prompt, "stream")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": target["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        span = self.langfuse.start_generation(
            name="llm.generate_stream",
            model=str(target["model"]),
            provider=str(target["provider"]),
            input_payload=messages,
            metadata={"temperature": temperature, "max_tokens": max_tokens, "stream": True, "profile": target["profile"]},
        )
        started_at = time.perf_counter()
        collected: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                async with client.stream("POST", str(target["base_url"]) + "/chat/completions", json=payload, headers=self._headers(str(target["api_key"]))) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content")
                            if token:
                                collected.append(token)
                                yield token
                        except json.JSONDecodeError:
                            continue
            output = "".join(collected)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            span.finish(
                output=output,
                metadata={"duration_ms": duration_ms, "status": "ok", "profile": target["profile"]},
                usage=self._estimate_usage(system_prompt, user_prompt, output),
            )
            self.langfuse.flush()
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("llm.stream_failed", error=str(exc))
            self.__class__._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN_SECONDS
            span.fail(error=str(exc), metadata={"status": "error", "profile": target["profile"]})
            self.langfuse.flush()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_chat_completions(self, messages: list[dict], *, temperature: float, max_tokens: int, target: dict[str, Any]) -> str | None:
        """Call the OpenAI-compatible ``/chat/completions`` endpoint."""
        payload = {
            "model": target["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            resp = await client.post(str(target["base_url"]) + "/chat/completions", json=payload, headers=self._headers(str(target["api_key"])))
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content")
            if content:
                logger.debug("llm.generate_ok", model=target["model"], chars=len(content), profile=target["profile"])
            return content

    def _headers(self, api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _resolve_runtime_target(self, system_prompt: str, user_prompt: str, tenant_key: str) -> dict[str, Any]:
        target = {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": self.api_key,
            "profile": "default",
        }
        enterprise_model = (settings.llm_enterprise_model_name or "").strip()
        enterprise_base_url = (settings.llm_enterprise_api_base_url or self.base_url).rstrip("/")
        if not settings.llm_enterprise_enabled or not enterprise_model or not enterprise_base_url:
            return target

        combined_text = f"{system_prompt}\n{user_prompt}".lower()
        keyword_hit = any(keyword.lower() in combined_text for keyword in settings.llm_enterprise_keyword_list)
        tenant_forced = tenant_key in settings.llm_enterprise_force_tenant_list
        canary_hit = in_canary_bucket(
            tenant_key,
            percent=settings.llm_enterprise_canary_percent,
            seed=settings.llm_enterprise_canary_seed,
        )
        if not (keyword_hit or tenant_forced or canary_hit):
            return target

        return {
            "provider": self.provider,
            "base_url": enterprise_base_url,
            "model": enterprise_model,
            "api_key": settings.llm_enterprise_api_key or self.api_key,
            "profile": "enterprise",
        }

    async def _resolve_runtime_target_async(self, system_prompt: str, user_prompt: str, tenant_key: str) -> dict[str, Any]:
        target = self._resolve_runtime_target(system_prompt, user_prompt, tenant_key)
        active_override = await self._get_active_model_override(
            tenant_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if active_override:
            target.update(active_override)
        return target

    async def _get_active_model_override(
        self,
        tenant_key: str,
        *,
        system_prompt: str = "",
        user_prompt: str = "",
    ) -> dict[str, Any] | None:
        redis_client = get_redis()
        owns_client = False
        if redis_client is None:
            redis_client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            owns_client = True
        try:
            try:
                raw = await redis_client.get(f"llm:active_model:{tenant_key}")
            except Exception:
                return None
            if not raw:
                return None
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return None
            if not isinstance(payload, dict):
                return None

            canary_percent = max(0, min(int(payload.get("canary_percent") or 0), 100))
            if 0 < canary_percent < 100:
                previous_payload = await self._get_previous_active_model(redis_client, tenant_key)
                if previous_payload:
                    bucket_key = self._registry_rollout_bucket_key(
                        tenant_key=tenant_key,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )
                    if not in_canary_bucket(
                        bucket_key,
                        percent=canary_percent,
                        seed=settings.llm_enterprise_canary_seed,
                    ):
                        resolved_previous = self._coerce_registry_target(previous_payload)
                        if resolved_previous:
                            resolved_previous["profile"] = "registry_previous_active"
                            resolved_previous["rollout_origin_model_id"] = str(payload.get("model_id") or "")
                            resolved_previous["rollout_canary_percent"] = canary_percent
                            return resolved_previous

            resolved_active = self._coerce_registry_target(payload)
            if resolved_active is None:
                return None
            if 0 < canary_percent < 100:
                resolved_active["profile"] = "registry_canary_active"
                resolved_active["rollout_canary_percent"] = canary_percent
            return resolved_active
        finally:
            if owns_client:
                await redis_client.aclose()

    async def _get_previous_active_model(self, redis_client: Redis, tenant_key: str) -> dict[str, Any] | None:
        try:
            raw = await redis_client.get(f"llm:previous_active_model:{tenant_key}")
        except Exception:
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _coerce_registry_target(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        base_url = str(payload.get("base_url") or "").rstrip("/")
        model = str(payload.get("model") or "").strip()
        if not base_url or not model:
            return None
        target = {
            "provider": str(payload.get("provider") or self.provider),
            "base_url": base_url,
            "model": model,
            "api_key": str(payload.get("api_key") or ""),
            "profile": str(payload.get("profile") or "registry_active"),
        }
        model_id = str(payload.get("model_id") or "").strip()
        if model_id:
            target["model_id"] = model_id
        return target

    def _registry_rollout_bucket_key(self, *, tenant_key: str, system_prompt: str, user_prompt: str) -> str:
        return f"{tenant_key}\n{system_prompt.strip()}\n{user_prompt.strip()}"

    def _estimate_usage(self, system_prompt: str, user_prompt: str, output: str) -> dict[str, int]:
        prompt_tokens = self._approx_token_count(system_prompt) + self._approx_token_count(user_prompt)
        completion_tokens = self._approx_token_count(output)
        return {
            "input": prompt_tokens,
            "output": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        }

    def _approx_token_count(self, text: str) -> int:
        content = (text or "").strip()
        if not content:
            return 0
        words = len(content.split())
        if words > 1:
            return words
        return max(1, len(content) // 2)
