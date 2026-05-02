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
from app.training.executor import describe_training_runtime


class LLMTrainingService:
    ACTIVE_MODEL_KEY_PREFIX = "llm:active_model:"
    PREVIOUS_ACTIVE_MODEL_KEY_PREFIX = "llm:previous_active_model:"
    OLLAMA_ADAPTER_SUPPORTED_PREFIXES = ("llama2", "llama3", "llama3.1", "llama3.2", "mistral", "gemma")
    TERMINAL_JOB_STATUSES = {"completed", "failed", "killed"}
    FAILURE_PATTERNS = (
        ("training_runtime_stale", "runtime_stale", True, "检查 Celery worker、Redis 心跳与训练执行器超时配置"),
        ("training_plan_only_result", "plan_only_result", False, "当前训练执行器仅返回计划结果，需要切换到真实训练运行时"),
        ("publish_command_failed", "publish_command_failed", True, "检查发布命令、Ollama 挂载路径与模型目录"),
        ("artifact_dir_missing", "artifact_missing", False, "检查训练产物目录是否生成并已挂载"),
        ("adapter_manifest_missing", "artifact_manifest_missing", False, "检查训练产物是否完整导出 adapter_manifest.json"),
        ("unsupported_ollama_adapter_base_model", "unsupported_base_model", False, "切换到受支持的基座模型或启用 merged model 导出"),
        ("all_health_checks_failed", "serving_verification_failed", True, "检查推理服务健康探针、网络连通性与模型注册状态"),
    )

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

    async def reconcile_jobs(
        self,
        jobs: list[LLMTrainingJob],
        *,
        runtime_payloads: dict[str, dict[str, Any]] | None = None,
        stale_after_seconds: int | None = None,
    ) -> dict[str, int]:
        stats = {
            "scanned": 0,
            "changed": 0,
            "stale_failed": 0,
            "plan_only_failed": 0,
        }
        for job in jobs:
            stats["scanned"] += 1
            runtime_payload = None
            if runtime_payloads and job.runtime_task_id:
                runtime_payload = runtime_payloads.get(job.runtime_task_id)
            changed = await self.reconcile_job_runtime_state(job, runtime_payload, stale_after_seconds=stale_after_seconds)
            if not changed:
                continue
            stats["changed"] += 1
            if (job.error_message or "").startswith("training_runtime_"):
                stats["stale_failed"] += 1
            if (job.error_message or "") == "training_plan_only_result":
                stats["plan_only_failed"] += 1
        return stats

    async def reconcile_model_registry_states(self, tenant_id: str, models: list[LLMModelRegistry] | None = None) -> bool:
        records = models if models is not None else await self.list_models(tenant_id, limit=200)
        active_payload = await self.get_active_model(tenant_id)
        active_model_id = str((active_payload or {}).get("model_id") or "").strip() or None
        changed = False
        for model in records:
            should_be_active = active_model_id == model.id if active_model_id else bool(model.is_active)
            expected_status = "active" if should_be_active else self._infer_inactive_model_status(model)
            if model.is_active != should_be_active:
                model.is_active = should_be_active
                changed = True
            if (model.status or "") != expected_status:
                model.status = expected_status
                changed = True
        if changed:
            await self.db.flush()
        return changed

    async def get_model(self, tenant_id: str, model_id: str) -> LLMModelRegistry | None:
        row = await self.db.execute(select(LLMModelRegistry).where(LLMModelRegistry.id == model_id, LLMModelRegistry.tenant_id == tenant_id))
        return row.scalar_one_or_none()

    @classmethod
    def supports_ollama_adapter_base_model(cls, base_model: str) -> bool:
        normalized = str(base_model or "").strip().lower()
        if not normalized:
            return False
        if "tinyllama" in normalized or "open_llama" in normalized:
            return False
        patterns = (
            r"(?:^|[/: _-])llama(?:[ _-]?)(?:2|3(?:\.\d+)?)(?:$|[/: _-])",
            r"(?:^|[/: _-])mistral(?:$|[/: _-])",
            r"(?:^|[/: _-])gemma(?:2)?(?:$|[/: _-])",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

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

    async def get_previous_active_model(self, tenant_id: str) -> dict[str, Any] | None:
        if self.redis is None:
            return None
        raw = await self.redis.get(self._previous_active_model_key(tenant_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def summarize_rollout(self, tenant_id: str, *, limit: int = 100) -> dict[str, Any]:
        jobs = await self.list_jobs(tenant_id, limit=max(limit, 1))
        models = await self.list_models(tenant_id, limit=max(limit, 1))
        active = await self.get_active_model(tenant_id)
        previous_active = await self.get_previous_active_model(tenant_id)
        executor_runtime = describe_training_runtime()

        job_status_counts: dict[str, int] = {}
        job_stage_counts: dict[str, int] = {}
        model_status_counts: dict[str, int] = {}
        publish_state_counts = {"published": 0, "publish_ready": 0, "not_ready": 0}
        pending_jobs = 0
        running_jobs = 0
        failed_jobs = 0
        active_models = 0
        canary_models = 0

        for job in jobs:
            status = str(job.status or "unknown")
            stage = str(job.stage or "unknown")
            job_status_counts[status] = job_status_counts.get(status, 0) + 1
            job_stage_counts[stage] = job_stage_counts.get(stage, 0) + 1
            if status == "pending":
                pending_jobs += 1
            elif status == "running":
                running_jobs += 1
            elif status == "failed":
                failed_jobs += 1

        for model in models:
            status = str(model.status or "unknown")
            model_status_counts[status] = model_status_counts.get(status, 0) + 1
            metrics = self._load_json(getattr(model, "metrics_json", None))
            publish_result = metrics.get("publish_result") if isinstance(metrics.get("publish_result"), dict) else {}
            if publish_result.get("published") is True or str(getattr(model, "provider", "")).lower() == "ollama":
                publish_state_counts["published"] += 1
            elif publish_result.get("publish_ready") is True:
                publish_state_counts["publish_ready"] += 1
            else:
                publish_state_counts["not_ready"] += 1
            if bool(getattr(model, "is_active", False)):
                active_models += 1
            if int(getattr(model, "canary_percent", 0) or 0) > 0:
                canary_models += 1

        latest_job = _serialize_training_job_brief(jobs[0]) if jobs else None
        latest_model = _serialize_registry_model_brief(models[0]) if models else None
        return {
            "tenant_id": tenant_id,
            "jobs": {
                "total": len(jobs),
                "pending": pending_jobs,
                "running": running_jobs,
                "failed": failed_jobs,
                "status_counts": job_status_counts,
                "stage_counts": job_stage_counts,
                "latest": latest_job,
            },
            "models": {
                "total": len(models),
                "active": active_models,
                "canary": canary_models,
                "status_counts": model_status_counts,
                "publish_state_counts": publish_state_counts,
                "latest": latest_model,
            },
            "active_model": active,
            "previous_active_model": previous_active,
            "can_rollback": bool(previous_active and previous_active.get("model_id")),
            "auto_activate_enabled": bool(settings.llm_training_auto_activate),
            "publish_enabled": bool(settings.llm_training_publish_enabled),
            "deploy_verify_enabled": bool(settings.llm_training_deploy_verify_enabled),
            "deploy_fail_rollback": bool(settings.llm_training_deploy_fail_rollback),
            "executor_runtime": executor_runtime,
        }

    async def summarize_deployment(self, tenant_id: str, *, limit: int = 20) -> dict[str, Any]:
        jobs = await self.list_jobs(tenant_id, limit=max(limit, 1))
        models = await self.list_models(tenant_id, limit=max(limit, 1))
        active = await self.get_active_model(tenant_id)
        previous_active = await self.get_previous_active_model(tenant_id)
        verification_by_model_id: dict[str, dict[str, Any]] = {}

        publish_counts = {"published": 0, "publish_ready": 0, "failed": 0, "unknown": 0}
        verify_counts = {"verified": 0, "failed": 0, "unknown": 0}
        failure_category_counts: dict[str, int] = {}
        recent_failures: list[dict[str, Any]] = []
        latest_job = jobs[0] if jobs else None
        latest_model = models[0] if models else None

        for job in jobs:
            result_payload = self._load_json(getattr(job, "result_json", None))
            verification = result_payload.get("deployment_verification") if isinstance(result_payload.get("deployment_verification"), dict) else None
            activated_model_id = str(getattr(job, "activated_model_id", "") or "").strip()
            if activated_model_id and verification:
                verification_by_model_id[activated_model_id] = verification

        for model in models:
            metrics = self._load_json(model.metrics_json)
            publish_result = metrics.get("publish_result") if isinstance(metrics.get("publish_result"), dict) else {}
            verify_result = metrics.get("verify_result") if isinstance(metrics.get("verify_result"), dict) else {}
            if not verify_result:
                fallback_verify = verification_by_model_id.get(str(model.id))
                verify_result = fallback_verify if isinstance(fallback_verify, dict) else {}
            if bool(publish_result.get("published")) or str(model.status or "") in {"published", "active"}:
                publish_counts["published"] += 1
            elif bool(publish_result.get("publish_ready")):
                publish_counts["publish_ready"] += 1
            elif publish_result:
                publish_counts["failed"] += 1
            else:
                publish_counts["unknown"] += 1

            if verify_result.get("ok") is True:
                verify_counts["verified"] += 1
            elif verify_result:
                verify_counts["failed"] += 1
            else:
                verify_counts["unknown"] += 1

            if publish_result.get("published") is False or verify_result.get("ok") is False:
                failure_category = self.classify_failure(
                    str(publish_result.get("reason") or verify_result.get("reason") or verify_result.get("message") or "")
                )
                failure_category_counts[failure_category["category"]] = failure_category_counts.get(failure_category["category"], 0) + 1
                recent_failures.append(
                    {
                        "model_id": model.id,
                        "model_name": model.model_name,
                        "status": model.status,
                        "publish_reason": publish_result.get("reason"),
                        "verify_reason": verify_result.get("reason") or verify_result.get("message"),
                        "failure_category": failure_category["category"],
                        "recoverable": failure_category["recoverable"],
                        "recommended_action": failure_category["recommended_action"],
                        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
                    }
                )

        return {
            "tenant_id": tenant_id,
            "active_model": active,
            "previous_active_model": previous_active,
            "latest_job": _serialize_training_job_brief(latest_job) if latest_job else None,
            "latest_model": _serialize_registry_model_brief(latest_model) if latest_model else None,
            "publish_counts": publish_counts,
            "verify_counts": verify_counts,
            "failure_category_counts": failure_category_counts,
            "can_rollback": bool(previous_active and previous_active.get("model_id")),
            "recent_failures": recent_failures[:10],
            "auto_activate_enabled": bool(settings.llm_training_auto_activate),
            "publish_enabled": bool(settings.llm_training_publish_enabled),
            "deploy_verify_enabled": bool(settings.llm_training_deploy_verify_enabled),
            "deploy_fail_rollback": bool(settings.llm_training_deploy_fail_rollback),
        }

    def classify_failure(self, error_message: str | None) -> dict[str, Any]:
        normalized = str(error_message or "").strip()
        for marker, category, recoverable, recommended_action in self.FAILURE_PATTERNS:
            if marker and marker in normalized:
                return {
                    "category": category,
                    "recoverable": recoverable,
                    "recommended_action": recommended_action,
                }
        if normalized.startswith("training_runtime_"):
            return {
                "category": "runtime_failure",
                "recoverable": True,
                "recommended_action": "检查训练运行时、任务队列与依赖服务状态",
            }
        return {
            "category": "unknown_failure",
            "recoverable": False,
            "recommended_action": "查看训练任务日志并人工排查失败原因",
        }

    def build_failure_result(self, error_message: str | None, result: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(result or {})
        normalized_error = str(error_message or payload.get("error") or "").strip()
        classification = self.classify_failure(normalized_error)
        payload.update(
            {
                "ok": False,
                "error": normalized_error,
                "failure_classification": classification,
            }
        )
        return payload

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
                        result = {"ok": True, "url": url, "status_code": response.status_code, "attempts": attempts, "reason": "verified"}
                        await self._record_verify_outcome(model, result)
                        return result
                except httpx.HTTPError as exc:
                    attempts.append({"url": url, "error": str(exc)})
        result = {"ok": False, "url": None, "status_code": None, "attempts": attempts, "reason": "all_health_checks_failed"}
        await self._record_verify_outcome(model, result)
        return result

    async def update_job_stage(self, job_id: str, *, status: str, stage: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        job = await self.db.get(LLMTrainingJob, job_id)
        if job is None:
            raise ValueError("训练任务不存在")
        job.status = status
        job.stage = stage
        job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        normalized_result = dict(result) if isinstance(result, dict) else None
        if status == "failed":
            normalized_result = self.build_failure_result(error, normalized_result)
        if normalized_result is not None:
            job.result_json = json.dumps(normalized_result, ensure_ascii=False)
        if error is not None:
            job.error_message = error[:4000]
        if status in {"completed", "failed", "killed"}:
            job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.flush()

    async def reconcile_job_runtime_state(
        self,
        job: LLMTrainingJob,
        runtime_payload: dict[str, Any] | None = None,
        *,
        stale_after_seconds: int | None = None,
    ) -> bool:
        if await self.reconcile_job_result_consistency(job):
            return True

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stale_after = max(int(stale_after_seconds or settings.llm_training_runtime_stale_seconds), 30)
        existing_error = str(job.error_message or "").strip()
        if job.status not in self.TERMINAL_JOB_STATUSES and (
            existing_error.startswith("training_runtime_") or existing_error == "recovered_timeout"
        ):
            job.status = "failed"
            job.stage = "failed"
            job.updated_at = now
            job.completed_at = now
            await self.db.flush()
            return True
        runtime_item = None
        if runtime_payload:
            runtime_item = runtime_payload.get("item") if "item" in runtime_payload else runtime_payload

        if runtime_item:
            runtime_status = str(runtime_item.get("status") or "").strip().lower()
            runtime_stage = str(runtime_item.get("stage") or job.stage or "").strip() or job.stage
            runtime_error = str(runtime_item.get("error") or "").strip() or None
            runtime_result = runtime_payload.get("result") if isinstance(runtime_payload, dict) else None

            if runtime_status in self.TERMINAL_JOB_STATUSES:
                normalized_stage = runtime_stage
                if runtime_status == "completed":
                    normalized_stage = "completed"
                elif runtime_stage not in {"failed", "killed"}:
                    normalized_stage = runtime_status
                changed = (
                    job.status != runtime_status
                    or job.stage != normalized_stage
                    or (runtime_error and job.error_message != runtime_error[:4000])
                    or isinstance(runtime_result, dict)
                )
                job.status = runtime_status
                job.stage = normalized_stage or ("completed" if runtime_status == "completed" else "failed")
                if runtime_error:
                    job.error_message = runtime_error[:4000]
                if isinstance(runtime_result, dict):
                    normalized_result = (
                        self.build_failure_result(runtime_error, runtime_result)
                        if runtime_status == "failed"
                        else runtime_result
                    )
                    job.result_json = json.dumps(normalized_result, ensure_ascii=False)
                if changed:
                    job.updated_at = now
                    job.completed_at = now
                    await self.db.flush()
                return changed

            runtime_updated_at = self._resolve_runtime_reference_time(runtime_item)
            if runtime_status in {"pending", "running"} and runtime_updated_at is not None:
                if (now - runtime_updated_at).total_seconds() > stale_after:
                    job.status = "failed"
                    job.stage = "failed"
                    job.error_message = f"training_runtime_stale>{stale_after}s"
                    job.updated_at = now
                    job.completed_at = now
                    await self.db.flush()
                    return True

        if job.status in self.TERMINAL_JOB_STATUSES:
            return False

        job_reference = self._parse_datetime(job.updated_at.isoformat() if job.updated_at else None)
        if job_reference is not None and (now - job_reference).total_seconds() > stale_after:
            job.status = "failed"
            job.stage = "failed"
            job.error_message = f"training_runtime_missing>{stale_after}s"
            job.updated_at = now
            job.completed_at = now
            await self.db.flush()
            return True

        return False

    async def reconcile_job_result_consistency(self, job: LLMTrainingJob) -> bool:
        if job.status != "completed" or not job.result_json:
            return False
        payload = self._load_json(job.result_json)
        metadata = payload.get("executor_metadata") if isinstance(payload.get("executor_metadata"), dict) else {}
        mode = str(metadata.get("mode") or "").strip().lower()
        if mode != "plan_only":
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        job.status = "failed"
        job.stage = "failed"
        job.error_message = "training_plan_only_result"
        job.result_json = json.dumps(self.build_failure_result("training_plan_only_result", payload), ensure_ascii=False)
        job.updated_at = now
        job.completed_at = now
        await self.db.flush()
        return True

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
                    "message": "未启用训练产物发布开关",
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
                    "message": f"训练产物目录不存在: {artifact_dir}",
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
                    "message": f"缺少 adapter_manifest.json: {manifest_path}",
                },
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        adapter_dir_raw = str(manifest.get("adapter_dir") or "").strip()
        adapter_dir = Path(adapter_dir_raw).resolve() if adapter_dir_raw else None
        merged_model_dir_raw = str(manifest.get("merged_model_dir") or "").strip()
        merged_model_dir = Path(merged_model_dir_raw).resolve() if merged_model_dir_raw else None
        hf_base_model = str(manifest.get("hf_base_model") or model.base_model or "").strip()

        modelfile_path = artifact_dir / "Modelfile"
        if not modelfile_path.exists():
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "modelfile_missing",
                    "message": f"缺少 Modelfile: {modelfile_path}",
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
                    "message": "未配置训练产物发布命令",
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

        publish_mode = "full_model_import" if merged_model_dir and merged_model_dir.exists() else "adapter"
        if publish_mode == "adapter":
            normalized_base = hf_base_model.lower()
            if not self.supports_ollama_adapter_base_model(normalized_base):
                return await self._record_publish_outcome(
                    model,
                    {
                        "ok": False,
                        "publish_ready": False,
                        "published": False,
                        "reason": "unsupported_ollama_adapter_base_model",
                        "message": f"Ollama 适配器发布当前仅支持 {', '.join(self.OLLAMA_ADAPTER_SUPPORTED_PREFIXES)} 系列，当前基座为 {hf_base_model}",
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
                        "message": f"适配器目录不存在: {adapter_dir}",
                        "hf_base_model": hf_base_model,
                    },
                )
        else:
            if merged_model_dir is None or not merged_model_dir.exists():
                return await self._record_publish_outcome(
                    model,
                    {
                        "ok": False,
                        "publish_ready": False,
                        "published": False,
                        "reason": "merged_model_dir_missing",
                        "message": f"完整模型目录不存在: {merged_model_dir}",
                        "hf_base_model": hf_base_model,
                    },
                )

        target_model_name = str(model.model_name or "").strip()
        format_args = {
            "model_name": target_model_name,
            "target_model_name": target_model_name,
            "base_model": model.base_model,
            "artifact_dir": str(artifact_dir),
            "adapter_dir": str(adapter_dir) if adapter_dir else "",
            "merged_model_dir": str(merged_model_dir) if merged_model_dir else "",
            "modelfile_path": str(modelfile_path),
            "serving_base_url": model.serving_base_url,
            "serving_model_name": target_model_name,
        }
        command = command_template.format(**format_args)
        workdir = artifact_dir.resolve()
        env = {
            **os.environ,
            "OLLAMA_HOST": self._normalize_ollama_host(model.serving_base_url),
            "DOCMIND_TRAINING_ARTIFACT_DIR": str(artifact_dir),
            "DOCMIND_TRAINING_MODEFILE_PATH": str(modelfile_path),
            "DOCMIND_TRAINING_ADAPTER_DIR": str(adapter_dir) if adapter_dir else "",
            "DOCMIND_TRAINING_MERGED_MODEL_DIR": str(merged_model_dir) if merged_model_dir else "",
            "DOCMIND_TRAINING_TARGET_MODEL_NAME": target_model_name,
            "DOCMIND_TRAINING_PUBLISH_MODE": publish_mode,
        }
        configured_workdir = str(settings.llm_training_publish_workdir or "").strip()
        if configured_workdir:
            env["DOCMIND_TRAINING_PUBLISH_WORKDIR_CONFIG"] = configured_workdir

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
            error_message = stderr_text or stdout_text or f"发布命令退出码 {process.returncode}"
            if "no Modelfile or safetensors files found" in error_message and "ollama" in command_template.lower():
                target_dir = merged_model_dir if publish_mode == "full_model_import" else artifact_dir
                error_message = (
                    f"{error_message}；当前 Ollama 服务端无法直接读取发布目录 {target_dir}，"
                    "请确保 `reports` 目录已挂载到 ollama 容器且容器内路径一致。"
                )
            return await self._record_publish_outcome(
                model,
                {
                    "ok": False,
                    "publish_ready": False,
                    "published": False,
                    "reason": "publish_command_failed",
                    "message": error_message,
                    "command": command,
                    "artifact_dir": str(artifact_dir),
                    "modelfile_path": str(modelfile_path),
                    "workdir": str(workdir),
                    "publish_mode": publish_mode,
                    "merged_model_dir": str(merged_model_dir) if merged_model_dir else None,
                },
            )

        model.serving_model_name = target_model_name
        model.provider = "ollama"
        model.status = "published"
        model.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        metrics = self._load_json(model.metrics_json)
        metrics["publish_command"] = command
        metrics["published_at"] = model.updated_at.isoformat()
        metrics["publish_mode"] = publish_mode
        metrics["publish_result"] = {
            "ok": True,
            "publish_ready": True,
            "published": True,
            "reason": "published",
            "message": "训练产物已发布到服务端模型注册表",
            "serving_model_name": target_model_name,
            "publish_mode": publish_mode,
        }
        model.metrics_json = json.dumps(metrics, ensure_ascii=False)
        await self.db.flush()
        return {
            "ok": True,
            "publish_ready": True,
            "published": True,
            "reason": "published",
            "message": "训练产物已发布到服务端模型注册表",
            "command": command,
            "serving_model_name": target_model_name,
            "stdout": stdout_text[-2000:],
            "publish_mode": publish_mode,
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

    async def _record_verify_outcome(self, model: LLMModelRegistry, payload: dict[str, Any]) -> dict[str, Any]:
        model.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        metrics = self._load_json(getattr(model, "metrics_json", None))
        payload = {**payload, "verified_at": model.updated_at.isoformat()}
        metrics["verify_result"] = payload
        model.metrics_json = json.dumps(metrics, ensure_ascii=False)
        if payload.get("ok") is True and getattr(model, "status", None) == "published":
            model.status = "verified"
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

    def _infer_inactive_model_status(self, model: LLMModelRegistry) -> str:
        metrics = self._load_json(getattr(model, "metrics_json", None))
        publish_result = metrics.get("publish_result") if isinstance(metrics.get("publish_result"), dict) else {}
        if publish_result.get("published") is True or getattr(model, "provider", "") == "ollama":
            return "published"
        return "registered"

    def _resolve_runtime_reference_time(self, runtime_item: dict[str, Any]) -> datetime | None:
        stage_payload = runtime_item.get("stage_payload")
        if isinstance(stage_payload, dict):
            heartbeat_at = stage_payload.get("heartbeat_at")
            parsed = self._parse_datetime(str(heartbeat_at) if heartbeat_at else None)
            if parsed is not None:
                return parsed
        return self._parse_datetime(str(runtime_item.get("updated_at") or "") or None)

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _serialize_training_job_brief(item: LLMTrainingJob) -> dict[str, Any]:
    return {
        "id": item.id,
        "dataset_name": item.dataset_name,
        "status": item.status,
        "stage": item.stage,
        "target_model_name": item.target_model_name,
        "runtime_task_id": item.runtime_task_id,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _serialize_registry_model_brief(item: LLMModelRegistry) -> dict[str, Any]:
    metrics = {}
    if item.metrics_json:
        try:
            metrics = json.loads(item.metrics_json)
        except json.JSONDecodeError:
            metrics = {}
    publish_result = metrics.get("publish_result") if isinstance(metrics.get("publish_result"), dict) else {}
    return {
        "id": item.id,
        "model_name": item.model_name,
        "status": item.status,
        "is_active": bool(item.is_active),
        "canary_percent": int(item.canary_percent or 0),
        "published": bool(publish_result.get("published") is True or str(item.provider or "").lower() == "ollama"),
        "publish_ready": bool(publish_result.get("publish_ready") is True),
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
