"""Scheduled runtime maintenance tasks."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import redis

from celery_app import celery
from app.config import settings


@celery.task(bind=True, name="app.maintenance.tasks.runtime_maintenance_job")
def runtime_maintenance_job(self, cleanup_empty: bool = True):
    """Run runtime TTL maintenance and write audit trail."""
    tenant_ids = _list_runtime_tenants()
    try:
        stats = asyncio.run(_run_runtime_maintenance(cleanup_empty=cleanup_empty))
        alert = _build_alert(stats)
        for tenant_id in tenant_ids:
            asyncio.run(
                _write_audit(
                    tenant_id=tenant_id,
                    message=f"runtime maintenance completed: {json.dumps(stats, ensure_ascii=False)}",
                    metadata={"stats": stats, "alert": alert},
                )
            )
            if alert["triggered"]:
                asyncio.run(
                    _write_audit(
                        tenant_id=tenant_id,
                        action="runtime_maintenance_alert",
                        severity="medium",
                        result="warning",
                        message=f"runtime maintenance alert: {', '.join(alert['reasons'])}",
                        metadata={"stats": stats, "alert": alert},
                    )
                )
        return {"ok": True, "stats": stats, "tenants": tenant_ids, "alert": alert}
    except Exception as exc:  # noqa: BLE001
        for tenant_id in tenant_ids:
            asyncio.run(
                _write_audit(
                    tenant_id=tenant_id,
                    action="runtime_maintenance",
                    severity="high",
                    result="error",
                    message=f"runtime maintenance failed: {exc}",
                    metadata={"error": str(exc)},
                )
            )
        return {"ok": False, "error": str(exc), "tenants": tenant_ids}


async def _run_runtime_maintenance(*, cleanup_empty: bool) -> dict:
    client = redis.asyncio.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    stats = {
        "scanned_replay_keys": 0,
        "repaired_replay_ttl": 0,
        "removed_empty_replay": 0,
        "scanned_task_keys": 0,
        "repaired_task_ttl": 0,
        "scanned_task_indexes": 0,
        "repaired_task_index_ttl": 0,
    }
    try:
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match="runtime:replay:*", count=300)
            for key in keys or []:
                stats["scanned_replay_keys"] += 1
                ttl = await client.ttl(key)
                if ttl < 0:
                    await client.expire(key, settings.runtime_event_replay_ttl_seconds)
                    stats["repaired_replay_ttl"] += 1
                if cleanup_empty and (await client.llen(key)) <= 0:
                    await client.delete(key)
                    stats["removed_empty_replay"] += 1
            if cursor == 0:
                break

        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match="runtime:task:*", count=300)
            for key in keys or []:
                stats["scanned_task_keys"] += 1
                ttl = await client.ttl(key)
                if ttl < 0:
                    await client.expire(key, settings.runtime_task_retention_seconds)
                    stats["repaired_task_ttl"] += 1
            if cursor == 0:
                break

        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match="runtime:tasks:*", count=300)
            for key in keys or []:
                stats["scanned_task_indexes"] += 1
                ttl = await client.ttl(key)
                if ttl < 0:
                    await client.expire(key, settings.runtime_task_retention_seconds)
                    stats["repaired_task_index_ttl"] += 1
            if cursor == 0:
                break
    finally:
        await client.aclose()
    return stats


@celery.task(bind=True, name="app.maintenance.tasks.export_public_corpus_job", acks_late=True, max_retries=0)
def export_public_corpus_job(self, dataset_name: str, tenant_id: str = "public_cold_start", train_ratio: float = 0.9, actor_id: str | None = None):
    """Export public cold-start corpus asynchronously and persist runtime task progress."""
    task_id = self.request.id or ""
    description = f"公开语料导出任务: dataset={dataset_name}, tenant={tenant_id}"
    _upsert_runtime_task_record(
        task_id=task_id,
        tenant_id=tenant_id,
        task_type="public_corpus_export",
        status="running",
        description=description,
        stage="running",
        stage_payload={"dataset_name": dataset_name, "actor_id": actor_id},
    )
    try:
        result = _run_public_corpus_export(dataset_name=dataset_name, tenant_id=tenant_id, train_ratio=train_ratio)
        _upsert_runtime_task_record(
            task_id=task_id,
            tenant_id=tenant_id,
            task_type="public_corpus_export",
            status="completed",
            description=description,
            stage="completed",
            terminal=True,
            stage_payload=result,
        )
        return {"ok": True, **result, "task_id": task_id}
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        _upsert_runtime_task_record(
            task_id=task_id,
            tenant_id=tenant_id,
            task_type="public_corpus_export",
            status="failed",
            description=description,
            stage="failed",
            error=error,
            terminal=True,
            stage_payload={"ok": False, "dataset_name": dataset_name, "error": error},
        )
        return {"ok": False, "task_id": task_id, "tenant_id": tenant_id, "dataset_name": dataset_name, "error": error}


def _run_public_corpus_export(*, dataset_name: str, tenant_id: str, train_ratio: float) -> dict:
    from app.services.enterprise_tuning_service import EnterpriseTuningService
    from app.services.public_corpus_service import PublicCorpusService

    datasets_dir = Path(os.getenv("DOCMIND_SHARED_DATASETS_DIR") or (Path(__file__).resolve().parents[3] / "datasets"))
    reports_dir = Path(os.getenv("DOCMIND_REPORTS_DIR") or (Path(__file__).resolve().parents[3] / "reports"))
    dataset_root = datasets_dir / dataset_name
    if not dataset_root.exists():
        raise FileNotFoundError(f"公开语料目录不存在: {dataset_name}")

    records = PublicCorpusService(dataset_root).build_records()
    result = EnterpriseTuningService(db=None, reports_dir=reports_dir).export_records_bundle(
        tenant_id=tenant_id,
        source_label=dataset_name,
        records=records,
        train_ratio=float(train_ratio),
    )
    result["dataset_name"] = dataset_name
    result["record_count"] = len(records)
    return result


def _list_runtime_tenants() -> list[str]:
    client = redis.from_url(settings.redis_url, decode_responses=True)
    tenants: set[str] = set()
    cursor = 0
    while True:
        cursor, keys = client.scan(cursor=cursor, match="runtime:tasks:*", count=200)
        for key in keys or []:
            parts = key.split(":")
            if len(parts) >= 3 and parts[-1]:
                tenants.add(parts[-1])
        if cursor == 0:
            break
    if not tenants:
        tenants.add(settings.bootstrap_demo_admin_tenant_id or "default")
    return sorted(tenants)


def _build_alert(stats: dict) -> dict:
    reasons: list[str] = []
    repaired_total = int(stats.get("repaired_replay_ttl", 0) or 0) + int(stats.get("repaired_task_ttl", 0) or 0) + int(stats.get("repaired_task_index_ttl", 0) or 0)
    empty_replay = int(stats.get("removed_empty_replay", 0) or 0)
    if repaired_total >= settings.runtime_maintenance_alert_repaired_ttl_threshold:
        reasons.append(f"repaired_ttl_keys={repaired_total}")
    if empty_replay >= settings.runtime_maintenance_alert_empty_replay_threshold:
        reasons.append(f"removed_empty_replay={empty_replay}")
    return {"triggered": bool(reasons), "reasons": reasons}


def _upsert_runtime_task_record(
    *,
    task_id: str,
    tenant_id: str,
    task_type: str,
    status: str,
    description: str,
    stage: str,
    error: str | None = None,
    terminal: bool = False,
    stage_payload: dict | None = None,
) -> None:
    if not task_id:
        return
    client = redis.from_url(settings.redis_url)
    try:
        key = f"runtime:task:{task_id}"
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        payload = {
            "task_id": task_id,
            "type": task_type,
            "status": status,
            "description": description,
            "tool_use_id": None,
            "start_time": now,
            "end_time": now if terminal else None,
            "output_offset": 0,
            "retries": 0,
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


async def _write_audit(
    *,
    tenant_id: str,
    message: str,
    metadata: dict,
    action: str = "runtime_maintenance",
    result: str = "ok",
    severity: str = "low",
) -> None:
    conn = await asyncpg.connect(settings.postgres_dsn_sync)
    try:
        await conn.execute(
            """
            INSERT INTO security_audit_events (
                id, tenant_id, actor_id, action, target, result, severity, message, trace_id, metadata_json, created_at
            ) VALUES (
                $1, $2, NULL, $3, $4, $5, $6, $7, $8, $9, $10
            )
            """,
            str(uuid.uuid4()),
            tenant_id,
            action,
            "runtime:*",
            result,
            severity,
            message[:2000],
            str(uuid.uuid4()),
            json.dumps(metadata, ensure_ascii=False),
            datetime.now(timezone.utc).replace(tzinfo=None),
        )
    finally:
        await conn.close()
