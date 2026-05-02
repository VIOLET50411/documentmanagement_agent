"""Celery tasks for tenant training jobs, execution, deployment, and rollback."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import time

import redis
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from celery_app import celery
from app.config import settings
from app.models.db.llm_training import LLMTrainingJob
from app.services.llm_training_service import LLMTrainingService
from app.services.security_audit_service import SecurityAuditService
from app.training.executor import TrainingExecutionRequest, build_training_executor


@celery.task(
    bind=True,
    name="app.training.tasks.run_training_job",
    acks_late=True,
    max_retries=0,
    soft_time_limit=settings.llm_training_task_soft_time_limit_seconds,
    time_limit=settings.llm_training_task_time_limit_seconds,
)
def run_training_job(self, training_job_id: str):
    task_id = self.request.id or ""
    try:
        return asyncio.run(_run_training_job_async(training_job_id=training_job_id, runtime_task_id=task_id))
    except SoftTimeLimitExceeded as exc:
        return asyncio.run(
            _mark_job_failure_async(
                training_job_id=training_job_id,
                runtime_task_id=task_id,
                error=f"训练任务执行超时: {exc}",
                terminal_status="failed",
            )
        )
    except Exception as exc:  # noqa: BLE001
        return asyncio.run(
            _mark_job_failure_async(
                training_job_id=training_job_id,
                runtime_task_id=task_id,
                error=str(exc),
                terminal_status="failed",
            )
        )


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
    reports_dir = Path(settings.docmind_reports_dir)

    try:
        async with session_factory() as db:
            service = LLMTrainingService(db, redis_client=redis_client, reports_dir=reports_dir)
            job = await db.get(LLMTrainingJob, training_job_id)
            if job is None:
                raise ValueError("训练任务不存在")
            audit = SecurityAuditService(redis_client, db)

            await _persist_job_stage(service, db, training_job_id, status="running", stage="validating")
            await _audit_training_event(
                audit,
                tenant_id=job.tenant_id,
                user_id=job.created_by,
                trace_id=runtime_task_id,
                event_type="llm_training_started",
                message=f"训练任务开始执行: {job.dataset_name}",
                result="ok",
                metadata={"job_id": job.id, "dataset_name": job.dataset_name, "provider": job.provider},
            )
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

            await _persist_job_stage(service, db, training_job_id, status="running", stage="executing")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="running",
                stage="executing",
                payload={"provider": job.provider, "artifact_dir": str(artifact_dir)},
            )

            executor = build_training_executor(job.provider)
            execution_result = await _execute_with_heartbeat(
                executor=executor,
                request=request,
                service=service,
                db=db,
                training_job_id=training_job_id,
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                provider=job.provider,
                artifact_dir=str(artifact_dir),
            )

            await _persist_job_stage(service, db, training_job_id, status="running", stage="validating_artifact")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="running",
                stage="validating_artifact",
                payload={"artifact_dir": execution_result.get("artifact_dir")},
            )
            validated_result = executor.validate_result(execution_result)

            await _persist_job_stage(service, db, training_job_id, status="running", stage="registering")
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
            await _audit_training_event(
                audit,
                tenant_id=job.tenant_id,
                user_id=job.created_by,
                trace_id=runtime_task_id,
                event_type="llm_model_registered",
                message=f"训练产物已注册: {model.model_name}",
                result="ok",
                metadata={"job_id": job.id, "model_id": model.id, "artifact_dir": validated_result["artifact_dir"]},
            )
            await db.commit()

            deployment_verification = None
            publish_result = {
                "ok": False,
                "publish_ready": bool((validated_result.get("executor_metadata") or {}).get("publish_ready")),
                "published": False,
                "reason": "executor_not_published",
                "message": "训练执行器未声明产物已发布",
            }
            if job.activate_on_success and settings.llm_training_auto_activate:
                publish_result = await service.publish_model_artifact(tenant_id=job.tenant_id, model_id=model.id)
                await _audit_training_event(
                    audit,
                    tenant_id=job.tenant_id,
                    user_id=job.created_by,
                    trace_id=runtime_task_id,
                    event_type="llm_model_publish",
                    message=str(publish_result.get("message") or "训练产物发布结果已记录"),
                    result="ok" if publish_result.get("published") else "warning",
                    severity="medium" if publish_result.get("published") else "high",
                    metadata={"job_id": job.id, "model_id": model.id, "publish_result": publish_result},
                )
            publish_ready = bool(publish_result.get("publish_ready"))
            auto_activated = False
            if job.activate_on_success and settings.llm_training_auto_activate and publish_ready:
                await _persist_job_stage(service, db, training_job_id, status="running", stage="deploying")
                await _upsert_runtime_task(
                    runtime_task_id=runtime_task_id,
                    tenant_id=job.tenant_id,
                    training_job_id=job.id,
                    status="running",
                    stage="deploying",
                    payload={"model_id": model.id, "serving_model_name": publish_result.get("serving_model_name") or validated_result["serving_model_name"]},
                )
                await service.activate_model(tenant_id=job.tenant_id, model_id=model.id, actor_id=job.created_by)
                auto_activated = True
                await _audit_training_event(
                    audit,
                    tenant_id=job.tenant_id,
                    user_id=job.created_by,
                    trace_id=runtime_task_id,
                    event_type="llm_model_activated",
                    message=f"模型已激活: {model.model_name}",
                    result="ok",
                    metadata={"job_id": job.id, "model_id": model.id},
                )
                if settings.llm_training_deploy_verify_enabled:
                    deployment_verification = await service.verify_model_serving(tenant_id=job.tenant_id, model_id=model.id)
                    await _audit_training_event(
                        audit,
                        tenant_id=job.tenant_id,
                        user_id=job.created_by,
                        trace_id=runtime_task_id,
                        event_type="llm_model_verify",
                        message="训练模型部署校验完成" if deployment_verification.get("ok") else "训练模型部署校验失败",
                        result="ok" if deployment_verification.get("ok") else "error",
                        severity="low" if deployment_verification.get("ok") else "high",
                        metadata={"job_id": job.id, "model_id": model.id, "verify_result": deployment_verification},
                    )
                    if not deployment_verification.get("ok"):
                        if settings.llm_training_deploy_fail_rollback:
                            await service.rollback_active_model(tenant_id=job.tenant_id, actor_id=job.created_by)
                            await _audit_training_event(
                                audit,
                                tenant_id=job.tenant_id,
                                user_id=job.created_by,
                                trace_id=runtime_task_id,
                                event_type="llm_model_rollback",
                                message="部署校验失败，已自动回滚上一版模型",
                                result="warning",
                                severity="high",
                                metadata={"job_id": job.id, "model_id": model.id, "verify_result": deployment_verification},
                            )
                        raise RuntimeError(f"训练模型部署校验失败: {json.dumps(deployment_verification, ensure_ascii=False)}")

            result = {
                "ok": True,
                "job_id": job.id,
                "model_id": model.id,
                "artifact_dir": validated_result["artifact_dir"],
                "serving_base_url": validated_result["serving_base_url"],
                "serving_model_name": publish_result.get("serving_model_name") or validated_result["serving_model_name"],
                "activate_on_success": job.activate_on_success,
                "auto_activated": auto_activated,
                "publish_ready": publish_ready,
                "publish_result": publish_result,
                "executor_metadata": validated_result.get("executor_metadata") or {},
                "deployment_verification": deployment_verification,
            }
            await _persist_job_stage(training_job_id=training_job_id, service=service, db=db, status="completed", stage="completed", result=result)
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=job.tenant_id,
                training_job_id=job.id,
                status="completed",
                stage="completed",
                payload=result,
                terminal=True,
            )
            await _audit_training_event(
                audit,
                tenant_id=job.tenant_id,
                user_id=job.created_by,
                trace_id=runtime_task_id,
                event_type="llm_training_completed",
                message=f"训练任务完成: {job.dataset_name}",
                result="ok",
                metadata={"job_id": job.id, "model_id": model.id, "publish_ready": publish_ready, "auto_activated": auto_activated},
            )
            await db.commit()
            return result
    except SoftTimeLimitExceeded as exc:
        return await _mark_job_failure_async(
            training_job_id=training_job_id,
            runtime_task_id=runtime_task_id,
            error=f"训练任务执行超时: {exc}",
            terminal_status="failed",
            db_factory=session_factory,
            redis_client=redis_client,
            reports_dir=reports_dir,
        )
    except Exception as exc:  # noqa: BLE001
        return await _mark_job_failure_async(
            training_job_id=training_job_id,
            runtime_task_id=runtime_task_id,
            error=str(exc),
            terminal_status="failed",
            db_factory=session_factory,
            redis_client=redis_client,
            reports_dir=reports_dir,
        )
    finally:
        await redis_client.aclose()
        await engine.dispose()


async def _persist_job_stage(
    service: LLMTrainingService,
    db: AsyncSession,
    training_job_id: str,
    *,
    status: str,
    stage: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    await service.update_job_stage(training_job_id, status=status, stage=stage, result=result, error=error)
    await db.commit()


async def _execute_with_heartbeat(
    *,
    executor,
    request: TrainingExecutionRequest,
    service: LLMTrainingService,
    db: AsyncSession,
    training_job_id: str,
    runtime_task_id: str,
    tenant_id: str,
    provider: str,
    artifact_dir: str,
) -> dict:
    heartbeat_seconds = max(int(settings.llm_training_progress_heartbeat_seconds), 5)
    started_at = time.monotonic()
    execution_task = asyncio.create_task(executor.execute(request))
    while True:
        try:
            return await asyncio.wait_for(asyncio.shield(execution_task), timeout=heartbeat_seconds)
        except asyncio.TimeoutError:
            heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            elapsed_seconds = round(time.monotonic() - started_at, 1)
            await _persist_job_stage(service, db, training_job_id, status="running", stage="executing")
            await _upsert_runtime_task(
                runtime_task_id=runtime_task_id,
                tenant_id=tenant_id,
                training_job_id=training_job_id,
                status="running",
                stage="executing",
                payload={
                    "provider": provider,
                    "artifact_dir": artifact_dir,
                    "heartbeat_at": heartbeat_at,
                    "elapsed_seconds": elapsed_seconds,
                },
            )


async def _mark_job_failure_async(
    *,
    training_job_id: str,
    runtime_task_id: str,
    error: str,
    terminal_status: str,
    db_factory: async_sessionmaker[AsyncSession] | None = None,
    redis_client=None,
    reports_dir: Path | None = None,
) -> dict:
    tenant_id = "unknown"
    failure_classification = None
    if db_factory is None:
        engine = create_async_engine(
            settings.postgres_dsn,
            echo=settings.app_debug,
            pool_size=2,
            max_overflow=2,
            pool_timeout=settings.postgres_pool_timeout_seconds,
            pool_pre_ping=True,
        )
        db_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        owns_engine = True
    else:
        engine = None
        owns_engine = False

    local_redis = redis_client
    owns_redis = False
    if local_redis is None:
        local_redis = redis.asyncio.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        owns_redis = True

    try:
        async with db_factory() as db:
            service = LLMTrainingService(db, redis_client=local_redis, reports_dir=reports_dir or Path(settings.docmind_reports_dir))
            job = await db.get(LLMTrainingJob, training_job_id)
            if job is not None:
                tenant_id = job.tenant_id
                try:
                    failure_result = service.build_failure_result(error)
                    failure_classification = failure_result.get("failure_classification")
                    await service.update_job_stage(
                        training_job_id,
                        status=terminal_status,
                        stage="failed",
                        result=failure_result,
                        error=error,
                    )
                    await _audit_training_event(
                        SecurityAuditService(local_redis, db),
                        tenant_id=job.tenant_id,
                        user_id=job.created_by,
                        trace_id=runtime_task_id,
                        event_type="llm_training_failed",
                        message=f"训练任务失败: {error[:200]}",
                        result="error",
                        severity="high",
                        metadata={"job_id": job.id, "error": error[:1000], "failure_classification": failure_result.get("failure_classification")},
                    )
                    await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
            else:
                await db.rollback()
    finally:
        await _upsert_runtime_task(
            runtime_task_id=runtime_task_id,
            tenant_id=tenant_id,
            training_job_id=training_job_id,
            status=terminal_status,
            stage="failed",
            payload={"ok": False, "error": error, "failure_classification": failure_classification},
            error=error,
            terminal=True,
        )
        if owns_redis and local_redis is not None:
            await local_redis.aclose()
        if owns_engine and engine is not None:
            await engine.dispose()
    return {"ok": False, "job_id": training_job_id, "error": error}


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
        except Exception:  # noqa: BLE001
            return
    finally:
        await client.aclose()


async def _audit_training_event(
    audit: SecurityAuditService,
    *,
    tenant_id: str,
    user_id: str | None,
    trace_id: str,
    event_type: str,
    message: str,
    result: str,
    metadata: dict | None = None,
    severity: str = "low",
) -> None:
    try:
        await audit.log_event(
            tenant_id,
            event_type,
            severity,
            message,
            user_id=user_id,
            target="llm_training",
            result=result,
            trace_id=trace_id,
            metadata=metadata or {},
        )
    except Exception:
        return
