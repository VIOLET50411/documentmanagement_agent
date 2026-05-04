"""Thin facade services for domain-specific LLM training operations.

These facades decompose the monolithic LLMTrainingService into three
logical concerns while delegating to the original service for actual
implementation. This allows callers (and future refactoring) to depend
on narrower interfaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_training_service import LLMTrainingService


class TrainingJobService:
    """Manages training job lifecycle: create, list, get, reconcile."""

    def __init__(self, db: AsyncSession, redis_client=None, reports_dir: str | Path | None = None):
        self._svc = LLMTrainingService(db, redis_client=redis_client, reports_dir=reports_dir)

    async def create_job(self, **kwargs) -> tuple:
        return await self._svc.create_job(**kwargs)

    async def attach_runtime_task(self, job_id: str, runtime_task_id: str) -> None:
        return await self._svc.attach_runtime_task(job_id, runtime_task_id)

    async def list_jobs(self, tenant_id: str, limit: int = 50):
        return await self._svc.list_jobs(tenant_id, limit=limit)

    async def get_job(self, tenant_id: str, job_id: str):
        return await self._svc.get_job(tenant_id, job_id)

    async def reconcile_job_runtime_state(self, job, runtime_payload: dict) -> bool:
        return await self._svc.reconcile_job_runtime_state(job, runtime_payload)

    async def update_job_stage(self, job_id: str, **kwargs) -> None:
        return await self._svc.update_job_stage(job_id, **kwargs)


class ModelRegistryService:
    """Manages model registration, activation, approval, canary, rollback."""

    def __init__(self, db: AsyncSession, redis_client=None, reports_dir: str | Path | None = None):
        self._svc = LLMTrainingService(db, redis_client=redis_client, reports_dir=reports_dir)

    async def list_models(self, tenant_id: str, limit: int = 50):
        return await self._svc.list_models(tenant_id, limit=limit)

    async def get_model(self, tenant_id: str, model_id: str):
        return await self._svc.get_model(tenant_id, model_id)

    async def activate_model(self, **kwargs):
        return await self._svc.activate_model(**kwargs)

    async def record_model_approval(self, **kwargs):
        return await self._svc.record_model_approval(**kwargs)

    async def update_model_canary_percent(self, **kwargs):
        return await self._svc.update_model_canary_percent(**kwargs)

    async def rollback_active_model(self, **kwargs):
        return await self._svc.rollback_active_model(**kwargs)

    async def get_active_model(self, tenant_id: str):
        return await self._svc.get_active_model(tenant_id)

    async def reconcile_model_registry_states(self, tenant_id: str, models=None) -> bool:
        return await self._svc.reconcile_model_registry_states(tenant_id, models)


class DeploymentService:
    """Manages model publishing, verification, rollout summary, and retirement."""

    def __init__(self, db: AsyncSession, redis_client=None, reports_dir: str | Path | None = None):
        self._svc = LLMTrainingService(db, redis_client=redis_client, reports_dir=reports_dir)

    async def publish_model_artifact(self, **kwargs):
        return await self._svc.publish_model_artifact(**kwargs)

    async def verify_model_serving(self, **kwargs):
        return await self._svc.verify_model_serving(**kwargs)

    async def summarize_deployment(self, tenant_id: str, **kwargs):
        return await self._svc.summarize_deployment(tenant_id, **kwargs)

    async def summarize_rollout(self, tenant_id: str, **kwargs):
        return await self._svc.summarize_rollout(tenant_id, **kwargs)

    async def retry_failed_publications(self, **kwargs):
        return await self._svc.retry_failed_publications(**kwargs)

    async def retire_nonrecoverable_models(self, **kwargs):
        return await self._svc.retire_nonrecoverable_models(**kwargs)
