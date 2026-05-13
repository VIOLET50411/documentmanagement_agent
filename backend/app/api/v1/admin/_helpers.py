"""Shared helpers for admin sub-routers."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings
from app.dependencies import get_redis


REPORTS_DIR = Path(os.getenv("DOCMIND_REPORTS_DIR") or (Path(__file__).resolve().parents[4] / "reports"))
PUBLIC_DATASETS_DIR = Path(os.getenv("DOCMIND_SHARED_DATASETS_DIR") or (Path(__file__).resolve().parents[5] / "datasets"))


def _error_signature(error_message: str | None) -> str:
    if not error_message:
        return "unknown"
    text = error_message.strip().lower()
    text = re.sub(r"[0-9a-f]{8,}", "<hex>", text)
    text = re.sub(r"\d{2,}", "<num>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120]


def _parse_runtime_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).replace(tzinfo=None)
    except ValueError:
        return None


def _normalize_tool_decision_item(item: dict, *, source_hint: str | None = None) -> dict:
    metadata = item.get("metadata") or {}
    source = source_hint or str(item.get("source") or metadata.get("source") or "unknown")
    created_at = str(item.get("created_at") or item.get("timestamp") or "")
    return {
        "decision": str(item.get("decision") or item.get("result") or "unknown"),
        "reason": str(metadata.get("reason") or item.get("reason") or item.get("message") or "unknown"),
        "source": source,
        "tool_name": str(metadata.get("tool_name") or item.get("tool_name") or item.get("target") or "unknown"),
        "user_id": item.get("user_id") or item.get("actor_id"),
        "tenant_id": item.get("tenant_id"),
        "trace_id": item.get("trace_id"),
        "created_at": created_at,
        "channel": item.get("channel") or ("security_audit" if source == "security_audit" else "runtime"),
    }


def _merge_tool_decision_items(runtime_items: list[dict], audit_items: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, str, str, str, str], dict] = {}
    for raw_item, source_hint in [*[(item, "runtime") for item in runtime_items], *[(item, "security_audit") for item in audit_items]]:
        normalized = _normalize_tool_decision_item(raw_item, source_hint=source_hint)
        created_at = normalized.get("created_at") or ""
        parsed = _parse_runtime_iso(created_at)
        created_bucket = parsed.replace(second=0, microsecond=0).isoformat() if parsed else created_at[:16]
        key = (
            str(normalized.get("trace_id") or ""),
            str(normalized.get("tool_name") or ""),
            str(normalized.get("decision") or ""),
            str(normalized.get("reason") or ""),
            created_bucket,
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = normalized
            continue
        if existing.get("source") != "security_audit" and normalized.get("source") == "security_audit":
            normalized["channel"] = "merged"
            deduped[key] = normalized
        else:
            existing["channel"] = "merged"
    merged = list(deduped.values())
    merged.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return merged


def _serialize_training_job(item) -> dict:
    payload = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "source_tenant_id": item.source_tenant_id,
        "dataset_name": item.dataset_name,
        "status": item.status,
        "stage": item.stage,
        "provider": item.provider,
        "base_model": item.base_model,
        "target_model_name": item.target_model_name,
        "export_dir": item.export_dir,
        "manifest_path": item.manifest_path,
        "artifact_dir": item.artifact_dir,
        "runtime_task_id": item.runtime_task_id,
        "activated_model_id": item.activated_model_id,
        "train_records": item.train_records,
        "val_records": item.val_records,
        "activate_on_success": item.activate_on_success,
        "error_message": item.error_message,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
    if item.result_json:
        try:
            payload["result"] = json.loads(item.result_json)
        except json.JSONDecodeError:
            payload["result_raw"] = item.result_json
    return payload


def _serialize_registry_model(item) -> dict:
    metrics = None
    if item.metrics_json:
        try:
            metrics = json.loads(item.metrics_json)
        except json.JSONDecodeError:
            metrics = {"raw": item.metrics_json}
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "training_job_id": item.training_job_id,
        "model_name": item.model_name,
        "provider": item.provider,
        "serving_base_url": item.serving_base_url,
        "serving_model_name": item.serving_model_name,
        "base_model": item.base_model,
        "artifact_dir": item.artifact_dir,
        "source_export_dir": item.source_export_dir,
        "source_dataset_name": item.source_dataset_name,
        "status": item.status,
        "is_active": item.is_active,
        "canary_percent": item.canary_percent,
        "metrics": metrics,
        "notes": item.notes,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "activated_at": item.activated_at.isoformat() if item.activated_at else None,
    }


def _admin_cache_key(tenant_id: str, scope: str, *parts: object) -> str:
    suffix = ":".join(str(part) for part in parts if part is not None and str(part) != "")
    if suffix:
        return f"admin:cache:{tenant_id}:{scope}:{suffix}"
    return f"admin:cache:{tenant_id}:{scope}"


async def _get_admin_cached_payload(key: str) -> dict | None:
    redis_client = get_redis()
    if redis_client is None:
        return None
    try:
        raw = await redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _set_admin_cached_payload(key: str, payload: dict, ttl_seconds: int | None = None) -> dict:
    redis_client = get_redis()
    if redis_client is None:
        return payload
    try:
        await redis_client.set(
            key,
            json.dumps(payload, ensure_ascii=False),
            ex=max(int(ttl_seconds or settings.admin_summary_cache_ttl_seconds), 1),
        )
    except Exception:
        return payload
    return payload


async def _load_admin_cached_payload(
    key: str,
    loader: Callable[[], Awaitable[dict]],
    *,
    ttl_seconds: int | None = None,
) -> dict:
    cached = await _get_admin_cached_payload(key)
    if cached is not None:
        return cached
    payload = await loader()
    return await _set_admin_cached_payload(key, payload, ttl_seconds=ttl_seconds)


async def _seed_runtime_task(task_id: str, *, tenant_id: str, task_type: str, description: str, stage: str = "queued") -> None:
    redis_client = get_redis()
    if redis_client is None:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    payload = {
        "task_id": task_id,
        "type": task_type,
        "status": "pending",
        "description": description,
        "tool_use_id": None,
        "start_time": now,
        "end_time": None,
        "output_offset": 0,
        "retries": 0,
        "notified": False,
        "trace_id": task_id,
        "tenant_id": tenant_id,
        "session_id": None,
        "stage": stage,
        "error": None,
        "updated_at": now,
    }
    await redis_client.set(f"runtime:task:{task_id}", json.dumps(payload, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
    await redis_client.zadd(f"runtime:tasks:{tenant_id}", {task_id: datetime.now(timezone.utc).timestamp()})
    await redis_client.expire(f"runtime:tasks:{tenant_id}", settings.runtime_task_retention_seconds)


async def _get_runtime_task_payload(task_id: str, *, tenant_id: str, expected_type: str) -> dict:
    from app.agent.runtime.task_store import TERMINAL_STATUSES
    from app.agent.runtime.task_store import TaskStore
    from celery.result import AsyncResult

    from celery_app import celery

    store = TaskStore(get_redis(), retention_seconds=settings.runtime_task_retention_seconds)
    record = await store.get(task_id)
    if record is None or record.tenant_id != tenant_id or record.type != expected_type:
        return {"exists": False, "task_id": task_id}

    result = AsyncResult(task_id, app=celery)
    raw = result.result if result.ready() else None
    if result.ready() and record.status not in TERMINAL_STATUSES:
        if isinstance(raw, dict) and raw.get("ok", True):
            await store.complete(task_id)
        elif isinstance(raw, dict):
            await store.fail(task_id, str(raw.get("error") or f"{expected_type}_failed"))
        else:
            await store.fail(task_id, str(raw))
        record = await store.get(task_id) or record

    payload = {"exists": True, "item": asdict(record), "celery_state": result.state}
    if result.ready():
        payload["result"] = raw if isinstance(raw, dict) else {"value": str(raw)}
    return payload
