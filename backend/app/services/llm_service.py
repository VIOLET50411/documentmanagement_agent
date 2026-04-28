"""LLM service with OpenAI-compatible API support (Ollama/vLLM/remote providers)."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx
import structlog

from app.config import settings
from app.observability.langfuse_client import LangfuseObserver

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
            async with httpx.AsyncClient(timeout=5.0) as client:
                if self.provider == "ollama":
                    resp = await client.get(self.base_url.replace("/v1", "") + "/api/tags")
                    resp.raise_for_status()
                    tags = [item.get("name", "") for item in resp.json().get("models", [])]
                    has_model = any(tag.startswith(self.model.split(":")[0]) for tag in tags)
                    return {"enabled": True, "available": True, "provider": self.provider, "model": self.model, "model_pulled": has_model}

                resp = await client.get(self.base_url + "/models", headers=self._headers())
                resp.raise_for_status()
                return {"enabled": True, "available": True, "provider": self.provider, "model": self.model}
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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        span = self.langfuse.start_generation(
            name="llm.generate",
            model=self.model,
            provider=self.provider,
            input_payload=messages,
            metadata={"temperature": temperature, "max_tokens": max_tokens, "stream": False},
        )
        started_at = time.perf_counter()

        try:
            output = await self._call_chat_completions(messages, temperature=temperature, max_tokens=max_tokens)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            span.finish(
                output=output,
                metadata={"duration_ms": duration_ms, "status": "ok"},
                usage=self._estimate_usage(system_prompt, user_prompt, output or ""),
            )
            self.langfuse.flush()
            return output
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("llm.generate_failed", error=str(exc), provider=self.provider, model=self.model)
            self.__class__._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN_SECONDS
            span.fail(error=str(exc), metadata={"status": "error"})
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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        span = self.langfuse.start_generation(
            name="llm.generate_stream",
            model=self.model,
            provider=self.provider,
            input_payload=messages,
            metadata={"temperature": temperature, "max_tokens": max_tokens, "stream": True},
        )
        started_at = time.perf_counter()
        collected: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                async with client.stream("POST", self.base_url + "/chat/completions", json=payload, headers=self._headers()) as resp:
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
                metadata={"duration_ms": duration_ms, "status": "ok"},
                usage=self._estimate_usage(system_prompt, user_prompt, output),
            )
            self.langfuse.flush()
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("llm.stream_failed", error=str(exc))
            self.__class__._circuit_open_until = time.monotonic() + self._CIRCUIT_COOLDOWN_SECONDS
            span.fail(error=str(exc), metadata={"status": "error"})
            self.langfuse.flush()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_chat_completions(self, messages: list[dict], *, temperature: float, max_tokens: int) -> str | None:
        """Call the OpenAI-compatible ``/chat/completions`` endpoint."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            resp = await client.post(self.base_url + "/chat/completions", json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content")
            if content:
                logger.debug("llm.generate_ok", model=self.model, chars=len(content))
            return content

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
