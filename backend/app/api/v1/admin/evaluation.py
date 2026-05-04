"""Admin sub-router: evaluation, runtime metrics, export."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.db.user import User

from app.api.v1.admin._helpers import (
    REPORTS_DIR, _seed_runtime_task, _get_runtime_task_payload,
)

router = APIRouter()

@router.post("/evaluation/run")
async def run_evaluation(sample_limit: int = 100, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(db, get_redis(), reports_dir=REPORTS_DIR).run(
        current_user.tenant_id,
        sample_limit=max(sample_limit, 1),
        actor=current_user,
    )


@router.post("/evaluation/run-async")
async def run_evaluation_async(sample_limit: int = 100, current_user: User = Depends(require_role("ADMIN"))):
    from app.maintenance.tasks import run_evaluation_job

    task = run_evaluation_job.apply_async(
        args=(current_user.tenant_id, max(sample_limit, 1), current_user.id),
        queue=settings.celery_maintenance_queue,
    )
    await _seed_runtime_task(task.id, tenant_id=current_user.tenant_id, task_type="evaluation", description=f"评估任务: tenant={current_user.tenant_id}")
    return {"task_id": task.id, "status": "pending", "tenant_id": current_user.tenant_id, "sample_limit": max(sample_limit, 1)}

@router.get("/evaluation/tasks/{task_id}")
async def get_evaluation_task(task_id: str, current_user: User = Depends(require_role("ADMIN"))):
    return await _get_runtime_task_payload(task_id, tenant_id=current_user.tenant_id, expected_type="evaluation")


@router.get("/evaluation/latest")
async def get_latest_evaluation(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(None, get_redis(), reports_dir=REPORTS_DIR).latest(current_user.tenant_id)


@router.get("/evaluation/history")
async def get_evaluation_history(
    limit: int = 30,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(None, get_redis(), reports_dir=REPORTS_DIR).history(
        current_user.tenant_id,
        limit=max(limit, 1),
    )


@router.get("/evaluation/gate-summary")
async def get_evaluation_gate_summary(
    limit: int = 30,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(None, get_redis(), reports_dir=REPORTS_DIR).summarize_history(
        current_user.tenant_id,
        limit=max(limit, 1),
    )


@router.get("/evaluation/runtime-metrics")
async def get_runtime_metrics(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.runtime_evaluation_service import RuntimeEvaluationService

    data = await RuntimeEvaluationService(db, get_redis()).get_metrics(current_user.tenant_id)
    return data


@router.get("/evaluation/runtime-metrics/history")
async def get_runtime_metrics_history(limit: int = 30, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.runtime_evaluation_service import RuntimeEvaluationService

    return await RuntimeEvaluationService(db, get_redis()).get_history(current_user.tenant_id, limit=max(limit, 1))


@router.get("/evaluation/runtime-metrics/export", response_class=PlainTextResponse)
async def export_runtime_metrics(
    format: str = "csv",
    limit: int = 100,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.runtime_evaluation_service import RuntimeEvaluationService

    service = RuntimeEvaluationService(db, get_redis())
    if format == "json":
        payload = await service.get_history(current_user.tenant_id, limit=max(limit, 1))
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return await service.export_csv(current_user.tenant_id, limit=max(limit, 1))


@router.post("/reindex")
async def reindex_documents(limit: int | None = None, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.index_sync_service import IndexSyncService

    return await IndexSyncService(db).reindex_tenant(current_user.tenant_id, limit=limit)
