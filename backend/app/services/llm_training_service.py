"""Training-job orchestration and tenant model registry service."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.llm_training import LLMModelRegistry, LLMTrainingJob


class LLMTrainingService:
    ACTIVE_MODEL_KEY_PREFIX = "llm:active_model:"
    PREVIOUS_ACTIVE_MODEL_KEY_PREFIX = "llm:previous_active_model:"
    OLLAMA_ADAPTER_SUPPORTED_PREFIXES = ("llama", "mistral", "gemma")

    def __init__(self, db: AsyncSession, redis_client=None, reports_dir: str | Path | None = None):
        self.db = db
        self.redis = redis_client
        self.reports_dir = Path(reports_dir) if reports_dir is not None else Path(settings.docmind_reports_dir)

    async def create_job(
        self,
        *,
        tenant_id: str,
        source_tenant_id: str,
        dataset_name: str,
        export_dir: str | None,
        base_model: str | None,
        provider: str | None,
        activate_on_success: bool,
        actor_id: str | None,
    ) -> tuple[LLMTrainingJob, dict[str, Any]]:
        summary = self._resolve_export_summary(source_tenant_id=source_tenant_id, dataset_name=dataset_name, export_dir=export_dir)
        readiness = summary.get("training_readiness") or {}
        train_records = int(readiness.get("train_records") or 0)
        val_records = int(readiness.get("val_records") or 0)
        if train_records < settings.llm_training_min_train_records:
            raise ValueError(f"训练样本不足，至少需要 {settings.llm_training_min_train_records} 条，当前 {train_records} 条")

        model_stub = self._build_target_model_name(tenant_id=tenant_id, dataset_name=dataset_name)
        job = LLMTrainingJob(
            tenant_id=tenant_id,
            source_tenant_id=source_tenant_id,
            dataset_name=dataset_name,
            status="pending",
            stage="queued",
            provider=(provider or settings.llm_training_provider or "mock").strip(),
            base_model=(base_model or settings.llm_training_base_model or settings.llm_enterprise_model_name or settings.llm_model_name).strip(),
            target_model_name=model_stub,
            export_dir=str(summary.get("export_dir") or ""),
            manifest_path=str(summary.get("manifest_path") or ""),
            train_records=train_records,
            val_records=val_records,
            activate_on_success=bool(activate_on_success),
            config_json=json.dumps(
                {
                    "dataset_name": dataset_name,
                    "source_tenant_id": source_tenant_id,
                    "export_dir": str(summary.get("export_dir") or ""),
                    "paths": summary.get("paths") or {},
                },
                ensure_ascii=False,
            ),
            created_by=actor_id,
        )
        self.db.add(job)
        await self.db.flush()
        return job, summary

    async def attach_runtime_task(self, job_id: str, runtime_task_id: str) -> None:
        await self.db.execute(update(LLMTrainingJob).where(LLMTrainingJob.id == job_id).values(runtime_task_id=runtime_task_id))
        await self.db.flush()

    async def list_jobs(self, tenant_id: str, limit: int = 50) -> list[LLMTrainingJob]:
        rows = await self.db.execute(
            select(LLMTrainingJob).where(LLMTrainingJob.tenant_id == tenant_id).order_by(LLMTrainingJob.created_at.desc()).limit(max(limit, 1))
        )
        return list(rows.scalars().all())

    async def get_job(self, tenant_id: str, job_id: str) -> LLMTrainingJob | None:
        row = await self.db.execute(select(LLMTrainingJob).where(LLMTrainingJob.id == job_id, LLMTrainingJob.tenant_id == tenant_id))
        return row.scalar_one_or_none()

    async def list_models(self, tenant_id: str, limit: int = 50) -> list[LLMModelRegistry]:
        rows = await self.db.execute(
            select(LLMModelRegistry).where(LLMModelRegistry.tenant_id == tenant_id).order_by(LLMModelRegistry.created_at.desc()).limit(max(limit, 1))
        )
        return list(rows.scalars().all())

    async def get_model(self, tenant_id: str, model_id: str) -> LLMModelRegistry | None:
        row = await self.db.execute(select(LLMModelRegistry).where(LLMModelRegistry.id == model_id, LLMModelRegistry.tenant_id == tenant_id))
        return row.scalar_one_or_none()

    async def activate_model(self, *, tenant_id: str, model_id: str, actor_id: str | None = None) -> LLMModelRegistry:
        model = await self.get_model(tenant_id, model_id)
        if model is None:
            raise ValueError("模型不存在")

        previous_active_payload = await self.get_active_model(tenant_id)

        await self.db.execute(update(LLMModelRegistry).where(LLMModelRegistry.tenant_id == tenant_id).values(is_active=False))
        model.is_active = True
        model.status = "active"
        model.activated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        model.updated_at = model.activated_at
        metrics = self._load_json(model.metrics_json)
        metrics["activated_by"] = actor_id
        model.metrics_json = json.dumps(metrics, ensure_ascii=False)
        await self.db.flush()

        if self.redis is not None:
            if previous_active_payload and previous_active_payload.get("model_id") != model.id:
                await self.redis.set(self._previous_active_model_key(tenant_id), json.dumps(previous_active_payload, ensure_ascii=False))
            await self.redis.set(self._active_model_key(tenant_id), json.dumps(self._serialize_active_model(model), ensure_ascii=False))
        return model

    async def update_model_canary_percent(
        self,
        *,
        tenant_id: str,
        model_id: str,
        canary_percent: int,
        actor_id: str | None = None,
    ) -> LLMModelRegistry:
        model = await self.get_model(tenant_id, model_id)
        if model is None:
            raise ValueError("模型不存在")
        normalized = min(max(int(canary_percent), 0), 100)
        model.canary_percent = normalized
        model.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        metrics = self._load_json(model.metrics_json)
        metrics["canary_updated_by"] = actor_id
        metrics["canary_updated_at"] = model.updated_at.isoformat()
        model.metrics_json = json.dumps(metrics, ensure_ascii=False)
        await self.db.flush()
        return model

    async def rollback_active_model(self, *, tenant_id: str, actor_id: str | None = None) -> dict[str, Any]:
        previous = None
        if self.redis is not None:
            raw = await self.redis.get(self._previous_active_model_key(tenant_id))
            if raw:
                try:
                    previous = json.loads(raw)
                except json.JSONDecodeError:
                    previous = None
        if not previous:
            raise ValueError("没有可回滚的上一版激活模型")

        previous_model_id = str(previous.get("model_id") or "").strip()
        if not previous_model_id:
            raise ValueError("上一版激活模型信息不完整")
        model = await self.activate_model(tenant_id=tenant_id, model_id=previous_model_id, actor_id=actor_id)
        return {"ok": True, "rolled_back_to": self._serialize_active_model(model)}

    async def get_active_model(self, tenant_id: str) -> dict[str, Any] | None:
        if self.redis is not None:
            raw = await self.redis.get(self._active_model_key(tenant_id))
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None

        row = await self.db.execute(select(LLMModelRegistry).where(LLMModelRegistry.tenant_id == tenant_id, LLMModelRegistry.is_active.is_(True)))
        model = row.scalar_one_or_none()
        if model is None:
            return None
        return self._serialize_active_model(model)

    async def verify_model_serving(self, *, tenant_id: str, model_id: str) -> dict[str, Any]:
        model = await self.get_model(tenant_id, model_id)
        if model is None:
            raise ValueError("模型不存在")

        base_url = (model.serving_base_url or "").rstrip("/")
        if not base_url:
            raise ValueError("模型未配置 serving_base_url")

        candidate_paths = []
        configured = (settings.llm_training_deploy_health_path or "").strip()
        if configured:
            candidate_paths.append(configured if configured.startswith("/") else f"/{configured}")
        candidate_paths.extend(["/models", "/health"])

        timeout = httpx.Timeout(max(int(settings.llm_training_deploy_verify_timeout_seconds), 3), connect=5.0)
        attempts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            for path in candidate_paths:
                url = f"{base_url}{path}"
                try:
                    response = await client.get(url)
                    attempts.append({"url": url, "status_code": response.status_code})
                    if response.status_code < 400:
                        return {"ok": True, "url": url, "status_code": response.status_code, "attempts": attempts}
                except httpx.HTTPError as exc:
                    attempts.append({"url": url, "error": str(exc)})
        return {"ok": False, "url": None, "status_code": None, "attempts": attempts}

    async def update_job_stage(self, job_id: str, *, status: str, stage: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        job = await self.db.get(LLMTrainingJob, job_id)
        if job is None:
            raise ValueError("训练任务不存在")
        job.status = status
        job.stage = stage
        job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if result is not None:
            job.result_json = json.dumps(result, ensure_ascii=False)
        if error is not None:
            job.error_message = error[:4000]
        if status in {"completed", "failed", "killed"}:
            job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.flush()

    async def register_model_from_job(
        self,
        *,
        job_id: str,
        serving_base_url: str,
        serving_model_name: str,
        artifact_dir: str,
        metrics: dict[str, Any],
        notes: str | None = None,
    ) -> LLMModelRegistry:
        job = await self.db.get(LLMTrainingJob, job_id)
        if job is None:
            raise ValueError("训练任务不存在")

        model = LLMModelRegistry(
            tenant_id=job.tenant_id,
            training_job_id=job.id,
            model_name=job.target_model_name,
            provider="openai-compatible",
            serving_base_url=serving_base_url,
            serving_model_name=serving_model_name,
            base_model=job.base_model,
            artifact_dir=artifact_dir,
            source_export_dir=job.export_dir,
            source_dataset_name=job.dataset_name,
            status="registered",
            is_active=False,
            canary_percent=0,
            config_json=job.config_json,
            metrics_json=json.dumps(metrics, ensure_ascii=False),
            notes=notes,
            created_by=job.created_by,
        )
        self.db.add(model)
        await self.db.flush()
        job.activated_model_id = model.id
        job.artifact_dir = artifact_dir
        await self.db.flush()
        return model

    async def publish_model_artifact(self, *, tenant_id: str, model_id: str) -> dict[str, Any]:
        model = await self.get_model(tenant_id, model_id)
        if model is None:
            raise ValueError("模型不存在")

        if not settings.llm_training_publish_enabled:
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "training_publish_disabled",
                    "message": "\u672a\u542f\u7528\u8bad\u7ec3\u4ea7\u7269\u53d1\u5e03\u5f00\u5173",
                },
            )

        artifact_dir = Path(model.artifact_dir or "")
        if not artifact_dir.exists():
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "artifact_dir_missing",
                    "message": f"\u8bad\u7ec3\u4ea7\u7269\u76ee\u5f55\u4e0d\u5b58\u5728: {artifact_dir}",
                },
            )

        manifest_path = artifact_dir / "adapter_manifest.json"
        if not manifest_path.exists():
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "adapter_manifest_missing",
                    "message": f"\u7f3a\u5c11 adapter_manifest.json: {manifest_path}",
                },
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        adapter_dir_raw = str(manifest.get("adapter_dir") or "").strip()
        adapter_dir = Path(adapter_dir_raw).resolve() if adapter_dir_raw else None
        hf_base_model = str(manifest.get("hf_base_model") or model.base_model or "").strip()
        normalized_base = hf_base_model.lower()
        if not any(prefix in normalized_base for prefix in self.OLLAMA_ADAPTER_SUPPORTED_PREFIXES):
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "unsupported_ollama_adapter_base_model",
                    "message": f"Ollama \u9002\u914d\u5668\u53d1\u5e03\u5f53\u524d\u4ec5\u652f\u6301 {', '.join(self.OLLAMA_ADAPTER_SUPPORTED_PREFIXES)} \u7cfb\u5217\uff0c\u5f53\u524d\u57fa\u5ea7\u4e3a {hf_base_model}",
                    "hf_base_model": hf_base_model,
                },
            )

        if adapter_dir is None or not adapter_dir.exists():
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "adapter_dir_missing",
                    "message": f"\u9002\u914d\u5668\u76ee\u5f55\u4e0d\u5b58\u5728: {adapter_dir}",
                    "hf_base_model": hf_base_model,
                },
            )

        modelfile_path = artifact_dir / "Modelfile"
        if not modelfile_path.exists():
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "modelfile_missing",
                    "message": f"\u7f3a\u5c11 Modelfile: {modelfile_path}",
                    "hf_base_model": hf_base_model,
                },
            )

        command_template = (settings.llm_training_publish_command or "").strip()
        if not command_template:
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "publish_command_missing",
                    "message": "\u672a\u542f\u7528\u8bad\u7ec3\u4ea7\u7269\u53d1\u5e03\u5f00\u5173",
                    "hf_base_model": hf_base_model,
                    "modelfile_path": str(modelfile_path),
                },
            )

        bootstrap = await self._ensure_publish_runtime(command_template)
        if not bootstrap.get("ok", False):
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "publish_runtime_bootstrap_failed",
                    "message": str(bootstrap.get("message") or "发布运行时自举失败"),
                    "bootstrap": bootstrap,
                    "hf_base_model": hf_base_model,
                },
            )

        target_model_name = str(model.model_name or "").strip()
        format_args = {
            "model_name": target_model_name,
            "target_model_name": target_model_name,
            "base_model": model.base_model,
            "artifact_dir": str(artifact_dir),
            "adapter_dir": str(adapter_dir),
            "modelfile_path": str(modelfile_path),
            "serving_base_url": model.serving_base_url,
            "serving_model_name": target_model_name,
        }
        command = command_template.format(**format_args)
        workdir = Path((settings.llm_training_publish_workdir or str(artifact_dir)).strip() or str(artifact_dir))
        workdir.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "OLLAMA_HOST": self._normalize_ollama_host(model.serving_base_url),
            "DOCMIND_TRAINING_ARTIFACT_DIR": str(artifact_dir),
            "DOCMIND_TRAINING_MODEFILE_PATH": str(modelfile_path),
            "DOCMIND_TRAINING_ADAPTER_DIR": str(adapter_dir),
            "DOCMIND_TRAINING_TARGET_MODEL_NAME": target_model_name,
        }

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_raw, stderr_raw = await process.communicate()
        stdout_text = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_raw.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "publish_command_failed",
                    "message": stderr_text or stdout_text or f"\u53d1\u5e03\u547d\u4ee4\u9000\u51fa\u7801 {process.returncode}",
                    "command": command,
                },
            )

        model.serving_model_name = target_model_name
        model.provider = "ollama"
        model.status = "published"
        model.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        metrics = self._load_json(model.metrics_json)
        metrics["publish_command"] = command
        metrics["published_at"] = model.updated_at.isoformat()
        model.metrics_json = json.dumps(metrics, ensure_ascii=False)
        await self.db.flush()
        return {
            "ok": True,
            "publish_ready": True,
            "published": True,
            "reason": "published",
            "message": "\u8bad\u7ec3\u4ea7\u7269\u5df2\u53d1\u5e03\u5230\u670d\u52a1\u7aef\u6a21\u578b\u6ce8\u518c\u8868",
            "command": command,
            "serving_model_name": target_model_name,
            "stdout": stdout_text[-2000:],
        }

    async def _record_publish_outcome(self, model: LLMModelRegistry, payload: dict[str, Any]) -> dict[str, Any]:
        model.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        metrics = self._load_json(model.metrics_json)
        metrics["publish_result"] = payload
        model.metrics_json = json.dumps(metrics, ensure_ascii=False)
        if payload.get("message"):
            model.notes = str(payload.get("message"))[:2000]
        await self.db.flush()
        return payload

    async def _ensure_publish_runtime(self, command_template: str) -> dict[str, Any]:
        if "ollama" not in command_template.lower():
            return {"ok": True, "bootstrapped": False, "runtime": "custom"}
        if shutil.which("ollama"):
            return {"ok": True, "bootstrapped": False, "runtime": "ollama_cli"}

        steps = [
            "if command -v apt-get >/dev/null 2>&1 && ! command -v zstd >/dev/null 2>&1; then apt-get update && apt-get install -y --no-install-recommends zstd && rm -rf /var/lib/apt/lists/*; fi",
            "if ! command -v curl >/dev/null 2>&1; then echo 'curl_not_found' >&2; exit 1; fi",
            "curl -fsSL https://ollama.com/install.sh | sh",
        ]
        process = await asyncio.create_subprocess_shell(
            "set -e; " + " && ".join(steps),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_raw, stderr_raw = await process.communicate()
        stdout_text = stdout_raw.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_raw.decode("utf-8", errors="replace").strip()
        if process.returncode != 0 or not shutil.which("ollama"):
            return {
                "ok": False,
                "bootstrapped": False,
                "runtime": "ollama_cli",
                "message": stderr_text or stdout_text or "ollama CLI 安装失败",
                "stdout": stdout_text[-2000:],
            }
        return {
            "ok": True,
            "bootstrapped": True,
            "runtime": "ollama_cli",
            "stdout": stdout_text[-2000:],
        }

    def _resolve_export_summary(self, *, source_tenant_id: str, dataset_name: str, export_dir: str | None) -> dict[str, Any]:
        if export_dir:
            manifest_path = Path(export_dir) / "manifest.json"
            if not manifest_path.exists():
                raise ValueError(f"\u8bad\u7ec3\u5bfc\u51fa\u76ee\u5f55\u4e0d\u5b58\u5728 manifest: {export_dir}")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["exists"] = True
            payload["manifest_path"] = str(manifest_path)
            payload["export_dir"] = str(Path(export_dir))
            return payload

        root = self.reports_dir / "domain_tuning" / source_tenant_id
        if not root.exists():
            raise ValueError(f"\u672a\u627e\u5230\u79df\u6237\u8bad\u7ec3\u5bfc\u51fa\u76ee\u5f55: {source_tenant_id}")

        manifests = sorted(root.glob(f"{dataset_name}_*/manifest.json"), key=lambda item: (item.stat().st_mtime, item.parent.name), reverse=True)
        if not manifests:
            manifests = sorted(root.glob("*/manifest.json"), key=lambda item: (item.stat().st_mtime, item.parent.name), reverse=True)
        if not manifests:
            raise ValueError(f"\u672a\u627e\u5230\u53ef\u8bad\u7ec3\u5bfc\u51fa\u7ed3\u679c: tenant={source_tenant_id}, dataset={dataset_name}")

        manifest_path = manifests[0]
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["exists"] = True
        payload["manifest_path"] = str(manifest_path)
        payload["export_dir"] = str(manifest_path.parent)
        return payload

    def _build_target_model_name(self, *, tenant_id: str, dataset_name: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", f"{tenant_id}-{dataset_name}").strip("-").lower()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{normalized}-{timestamp}"

    @classmethod
    def _active_model_key(cls, tenant_id: str) -> str:
        return f"{cls.ACTIVE_MODEL_KEY_PREFIX}{tenant_id}"

    @classmethod
    def _previous_active_model_key(cls, tenant_id: str) -> str:
        return f"{cls.PREVIOUS_ACTIVE_MODEL_KEY_PREFIX}{tenant_id}"

    def _load_json(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _serialize_active_model(self, model: LLMModelRegistry) -> dict[str, Any]:
        return {
            "model_id": model.id,
            "tenant_id": model.tenant_id,
            "provider": model.provider,
            "base_url": model.serving_base_url,
            "model": model.serving_model_name,
            "api_key": model.api_key or "",
            "profile": "registry_active",
            "artifact_dir": model.artifact_dir,
            "activated_at": model.activated_at.isoformat() if model.activated_at else None,
        }

    def _normalize_ollama_host(self, base_url: str | None) -> str:
        raw = (base_url or "").strip()
        if raw.endswith("/v1"):
            return raw[:-3]
        return raw.rstrip("/")
