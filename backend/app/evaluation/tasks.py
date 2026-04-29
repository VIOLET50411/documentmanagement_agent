"""Celery tasks for evaluation workflows."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import redis
from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from celery_app import celery
from app.agent.runtime.task_store import TERMINAL_STATUSES
from app.config import settings
from app.services.evaluation_service import EvaluationService

EVALUATION_TASK_LABEL = "\u8bc4\u4f30\u4efb\u52a1"


@celery.task(bind=True, name="app.evaluation.tasks.run_evaluation_job", acks_late=True, max_retries=0)
def run_evaluation_job(self, tenant_id: str, sample_limit: int = 100, actor_id: str | None = None):
    """Run evaluation asynchronously and write runtime task progress."""
    task_id = self.request.id or ""
    _upsert_runtime_task(
        task_id=task_id,
        tenant_id=tenant_id,
        status="running",
        description=f"{EVALUATION_TASK_LABEL}: tenant={tenant_id}",
        stage="running",
        retries=0,
    )
    try:
        result = asyncio.run(
            _run_evaluation_async(
                task_id=task_id,
                tenant_id=tenant_id,
                sample_limit=max(sample_limit, 1),
                actor_id=actor_id,
            )
        )
        _upsert_runtime_task(
            task_id=task_id,
            tenant_id=tenant_id,
            status="completed",
            description=f"{EVALUATION_TASK_LABEL}: tenant={tenant_id}",
            stage="completed",
            retries=0,
            terminal=True,
            stage_payload={"ok": True, "dataset_size": result.get("dataset_size")},
        )
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        _upsert_runtime_task(
            task_id=task_id,
            tenant_id=tenant_id,
            status="failed",
            description=f"{EVALUATION_TASK_LABEL}: tenant={tenant_id}",
            stage="failed",
            retries=0,
            error=str(exc),
            terminal=True,
            stage_payload={"ok": False, "error": str(exc)},
        )
        return {"ok": False, "error": str(exc), "tenant_id": tenant_id, "task_id": task_id}


async def _run_evaluation_async(*, task_id: str, tenant_id: str, sample_limit: int, actor_id: str | None) -> dict:
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
    try:
        async with session_factory() as db:
            actor = None
            if actor_id:
                from app.models.db.user import User

                actor = await db.get(User, actor_id)
            result = await EvaluationService(db, redis_client).run(
                tenant_id,
                sample_limit=sample_limit,
                actor=actor,
                progress_callback=lambda stage, payload: _notify_progress_async(
                    task_id=task_id or _current_task_id(),
                    tenant_id=tenant_id,
                    stage=stage,
                    payload=payload,
                ),
            )
            await db.commit()
            return result
    finally:
        await redis_client.aclose()
        await engine.dispose()


async def _notify_progress_async(*, task_id: str, tenant_id: str, stage: str, payload: dict[str, Any]) -> None:
    status = "running"
    terminal = False
    error = None
    if stage == "completed":
        status = "completed"
        terminal = True
    elif stage == "failed":
        status = "failed"
        terminal = True
        error = str(payload.get("error") or "evaluation_failed")
    _upsert_runtime_task(
        task_id=task_id,
        tenant_id=tenant_id,
        status=status,
        description=f"{EVALUATION_TASK_LABEL}: tenant={tenant_id}",
        stage=stage,
        retries=0,
        error=error,
        terminal=terminal,
        stage_payload=payload,
    )


def _current_task_id() -> str:
    if current_task is None:
        return ""
    return current_task.request.id or ""


def _upsert_runtime_task(
    *,
    task_id: str,
    tenant_id: str,
    status: str,
    description: str,
    stage: str | None,
    retries: int,
    error: str | None = None,
    terminal: bool = False,
    stage_payload: dict[str, Any] | None = None,
) -> None:
    if not task_id:
        return
    client = redis.from_url(settings.redis_url)
    try:
        key = f"runtime:task:{task_id}"
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        payload = {
            "task_id": task_id,
            "type": "evaluation",
            "status": status,
            "description": description,
            "tool_use_id": None,
            "start_time": now,
            "end_time": now if terminal else None,
            "output_offset": 0,
            "retries": retries,
            "notified": False,
            "trace_id": task_id,
            "tenant_id": tenant_id,
            "session_id": None,
            "stage": stage,
            "error": error[:2000] if error else None,
            "updated_at": now,
        }
        raw = client.get(key)
        if raw:
            try:
                existing = json.loads(raw)
            except json.JSONDecodeError:
                existing = {}
            if existing.get("status") in TERMINAL_STATUSES and not terminal:
                return
            payload["start_time"] = existing.get("start_time") or now
            payload["output_offset"] = existing.get("output_offset", 0)
            payload["notified"] = existing.get("notified", False)
            if not terminal:
                payload["end_time"] = existing.get("end_time")
        if stage_payload:
            payload["stage_payload"] = stage_payload
        client.set(key, json.dumps(payload, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
        index_key = f"runtime:tasks:{tenant_id}"
        client.zadd(index_key, {task_id: datetime.now(timezone.utc).timestamp()})
        client.expire(index_key, settings.runtime_task_retention_seconds)
    finally:
        client.close()
