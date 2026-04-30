"""Celery tasks for tenant training jobs, execution, deployment, and rollback."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from celery_app import celery
from app.config import settings
from app.models.db.llm_training import LLMTrainingJob
from app.services.llm_training_service import LLMTrainingService
from app.training.executor import TrainingExecutionRequest, build_training_executor


@celery.task(bind=True, name="app.training.tasks.run_training_job", acks_late=True, max_retries=0)
def run_training_job(self, training_job_id: str):
    task_id = self.request.id or ""
    return asyncio.run(_run_training_job_async(training_job_id=training_job_id, runtime_task_id=task_id))


async def _run_training_job_async(*, training_job_id: str, runtime_task_id: str) -> dict:
    engine = create_async_engine(
        settings.postgres_dsn,
        echo=settings.app_debug,
        pool_size=4,
        max_overflow=4,
        pool_timeout=settings.postgres_pool_timeout_seconds,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    redis_client = redis.asyncio.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    reports_dir = Path(__file__).resolve().parents[3] / "reports"

    try:
        async with session_factory() as db:
            service = LLMTrainingService(db, redis_client=redis_client, reports_dir=reports_dir)
            job = await db.get(LLMTrainingJob, training_job_id)
            if job is None:
                raise ValueError("训练任务不存在")

            await service.update_job_stage(training_job_id, status="running", stage="validating")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="running",
                stage="validating",
                payload={"job_id": job.id, "dataset_name": job.dataset_name},
            )

            manifest_path = Path(job.manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            readiness = manifest.get("training_readiness") or {}
            train_records = int(readiness.get("train_records") or 0)
            val_records = int(readiness.get("val_records") or 0)

            artifact_dir = reports_dir / settings.llm_training_artifacts_subdir / job.tenant_id / job.id
            request = TrainingExecutionRequest(
                job_id=job.id,
                tenant_id=job.tenant_id,
                dataset_name=job.dataset_name,
                base_model=job.base_model,
                export_dir=job.export_dir,
                manifest_path=job.manifest_path,
                target_model_name=job.target_model_name,
                train_records=train_records,
                val_records=val_records,
                artifact_dir=str(artifact_dir),
                provider=job.provider,
            )

            await service.update_job_stage(training_job_id, status="running", stage="executing")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="running",
                stage="executing",
                payload={"provider": job.provider, "artifact_dir": str(artifact_dir)},
            )

            executor = build_training_executor(job.provider)
            execution_result = await executor.execute(request)

            await service.update_job_stage(training_job_id, status="running", stage="validating_artifact")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="running",
                stage="validating_artifact",
                payload={"artifact_dir": execution_result.get("artifact_dir")},
            )
            validated_result = executor.validate_result(execution_result)

            await service.update_job_stage(training_job_id, status="running", stage="registering")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="running",
                stage="registering",
                payload={"artifact_dir": validated_result["artifact_dir"]},
            )

            model = await service.register_model_from_job(
                job_id=job.id,
                serving_base_url=validated_result["serving_base_url"],
                serving_model_name=validated_result["serving_model_name"],
                artifact_dir=validated_result["artifact_dir"],
                metrics={
                    "train_records": train_records,
                    "val_records": val_records,
                    "ready_for_lora": bool(readiness.get("ready_for_lora")),
                    "ready_for_sft": bool(readiness.get("ready_for_sft")),
                    "provider": job.provider,
                    "executor_metadata": validated_result.get("executor_metadata") or {},
                },
                notes=validated_result.get("notes") or "训练产物已注册，可继续接入真实推理服务部署。",
            )

            if job.activate_on_success and settings.llm_training_auto_activate:
                await service.update_job_stage(training_job_id, status="running", stage="deploying")
                await _upsert_runtime_task(
                    runtime_task_id=runtime_task_id,
                    tenant_id=job.tenant_id,
                    training_job_id=job.id,
                    status="running",
                    stage="deploying",
                    payload={"model_id": model.id, "serving_model_name": validated_result["serving_model_name"]},
                )
                await service.activate_model(tenant_id=job.tenant_id, model_id=model.id, actor_id=job.created_by)

            result = {
                "ok": True,
                "job_id": job.id,
                "model_id": model.id,
                "artifact_dir": validated_result["artifact_dir"],
                "serving_base_url": validated_result["serving_base_url"],
                "serving_model_name": validated_result["serving_model_name"],
                "activate_on_success": job.activate_on_success,
                "executor_metadata": validated_result.get("executor_metadata") or {},
            }
            await service.update_job_stage(training_job_id, status="completed", stage="completed", result=result)
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="completed",
                stage="completed",
                payload=result,
                terminal=True,
            )
            await db.commit()
            return result
    except Exception as exc:  # noqa: BLE001
        async with session_factory() as db:
            service = LLMTrainingService(db, redis_client=redis_client, reports_dir=reports_dir)
            try:
                await service.update_job_stage(training_job_id, status="failed", stage="failed", error=str(exc))
                await db.commit()
            except Exception:
                await db.rollback()
        await _upsert_runtime_task(
            runtime_task_id=runtime_task_id,
            tenant_id="unknown",
            training_job_id=training_job_id,
            status="failed",
            stage="failed",
            payload={"ok": False, "error": str(exc)},
            error=str(exc),
            terminal=True,
        )
        return {"ok": False, "job_id": training_job_id, "error": str(exc)}
    finally:
        await redis_client.aclose()
        await engine.dispose()


async def _upsert_runtime_task(
    *,
    runtime_task_id: str,
    tenant_id: str,
    training_job_id: str,
    status: str,
    stage: str,
    payload: dict,
    error: str | None = None,
    terminal: bool = False,
) -> None:
    if not runtime_task_id:
        return
    client = redis.asyncio.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        key = f"runtime:task:{runtime_task_id}"
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        existing = {}
        raw = await client.get(key)
        if raw:
            try:
                existing = json.loads(raw)
            except json.JSONDecodeError:
                existing = {}
        record = {
            "task_id": runtime_task_id,
            "type": "llm_training",
            "status": status,
            "description": f"模型训练任务: job={training_job_id}",
            "tool_use_id": None,
            "start_time": existing.get("start_time") or now,
            "end_time": now if terminal else existing.get("end_time"),
            "output_offset": existing.get("output_offset", 0),
            "retries": 0,
            "notified": existing.get("notified", False),
            "trace_id": runtime_task_id,
            "tenant_id": existing.get("tenant_id") or tenant_id,
            "session_id": None,
            "stage": stage,
            "stage_payload": payload,
            "error": error[:2000] if error else None,
            "updated_at": now,
        }
        await client.set(key, json.dumps(record, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
        if tenant_id != "unknown":
            await client.zadd(f"runtime:tasks:{tenant_id}", {runtime_task_id: datetime.now(timezone.utc).timestamp()})
            await client.expire(f"runtime:tasks:{tenant_id}", settings.runtime_task_retention_seconds)
    finally:
        await client.aclose()
