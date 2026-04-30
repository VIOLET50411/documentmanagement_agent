"""Training-job orchestration and tenant model registry service."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.llm_training import LLMModelRegistry, LLMTrainingJob


class LLMTrainingService:
    ACTIVE_MODEL_KEY_PREFIX = "llm:active_model:"
    PREVIOUS_ACTIVE_MODEL_KEY_PREFIX = "llm:previous_active_model:"

    def __init__(self, db: AsyncSession, redis_client=None, reports_dir: str | Path = "reports"):
        self.db = db
        self.redis = redis_client
        self.reports_dir = Path(reports_dir)

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

    def _resolve_export_summary(self, *, source_tenant_id: str, dataset_name: str, export_dir: str | None) -> dict[str, Any]:
        if export_dir:
            manifest_path = Path(export_dir) / "manifest.json"
            if not manifest_path.exists():
                raise ValueError(f"训练导出目录不存在 manifest: {export_dir}")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["exists"] = True
            payload["manifest_path"] = str(manifest_path)
            payload["export_dir"] = str(Path(export_dir))
            return payload

        root = self.reports_dir / "domain_tuning" / source_tenant_id
        if not root.exists():
            raise ValueError(f"未找到租户训练导出目录: {source_tenant_id}")

        manifests = sorted(root.glob(f"{dataset_name}_*/manifest.json"), key=lambda item: (item.stat().st_mtime, item.parent.name), reverse=True)
        if not manifests:
            manifests = sorted(root.glob("*/manifest.json"), key=lambda item: (item.stat().st_mtime, item.parent.name), reverse=True)
        if not manifests:
            raise ValueError(f"未找到可训练导出结果: tenant={source_tenant_id}, dataset={dataset_name}")

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
