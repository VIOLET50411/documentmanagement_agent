"""Admin API - user management, analytics, pipeline, security, and evaluation."""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.config import settings
from app.dependencies import get_db, get_minio_client, get_redis
from app.models.db.document import Document, DocumentChunk
from app.models.db.user import User
from app.models.schemas.user import UserResponse

router = APIRouter()
REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


def _error_signature(error_message: str | None) -> str:
    if not error_message:
        return "unknown"
    text = error_message.strip().lower()
    text = re.sub(r"[0-9a-f]{8,}", "<hex>", text)
    text = re.sub(r"\d{2,}", "<num>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120]


@router.get("/users", response_model=List[UserResponse])
async def list_users(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.auth_service import AuthService

    return await AuthService(db).list_users(tenant_id=current_user.tenant_id)


@router.get("/analytics/overview")
async def get_analytics_overview(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.analytics_service import AnalyticsService

    return await AnalyticsService(db).get_overview(tenant_id=current_user.tenant_id)


@router.get("/pipeline/status")
async def get_pipeline_status(current_user: User = Depends(require_role("ADMIN"))):
    redis = get_redis()
    if redis is None:
        return {"active": 0, "queued": 0, "failed": 0, "completed": 0}

    active = queued = failed = completed = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match="doc_progress:*", count=200)
        for key in keys or []:
            status = await redis.hget(key, "status")
            if status in ("queued", "parsing", "chunking", "indexing", "retrying"):
                active += 1
                queued += 1 if status == "queued" else 0
            elif status in ("failed", "partial_failed"):
                failed += 1
            elif status == "ready":
                completed += 1
        if cursor == 0:
            break
    return {"active": active, "queued": queued, "failed": failed, "completed": completed}


@router.get("/pipeline/jobs")
async def get_pipeline_jobs(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    base_query = select(Document).where(Document.tenant_id == current_user.tenant_id)
    if status:
        if status == "failed_family":
            base_query = base_query.where(Document.status.in_(["failed", "partial_failed"]))
        else:
            base_query = base_query.where(Document.status == status)
    total = int((await db.execute(select(func.count()).select_from(base_query.subquery()))).scalar() or 0)
    result = await db.execute(base_query.order_by(Document.updated_at.desc()).offset(max(offset, 0)).limit(max(limit, 1)))
    documents = result.scalars().all()
    redis = get_redis()
    jobs = []
    for document in documents:
        progress = await redis.hgetall(f"doc_progress:{document.id}") if redis is not None else {}
        jobs.append(
            {
                "doc_id": document.id,
                "title": document.title,
                "status": progress.get("status", document.status),
                "percentage": int(progress.get("percentage", 0) or 0),
                "task_id": progress.get("task_id"),
                "attempt": int(progress.get("attempt", 0) or 0),
                "detail": progress.get("detail"),
                "chunk_count": document.chunk_count,
                "file_size": document.file_size,
                "error_message": progress.get("error") or document.error_message,
                "updated_at": progress.get("updated_at") or document.updated_at.isoformat(),
            }
        )
    return {"jobs": jobs, "total": total, "offset": max(offset, 0), "limit": max(limit, 1)}


@router.post("/pipeline/{doc_id}/retry")
async def retry_pipeline_job(
    doc_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_service import DocumentService

    result = await DocumentService(db, get_minio_client()).enqueue_retry(doc_id=doc_id, user=current_user)
    return result


@router.post("/pipeline/retry-failed")
async def retry_failed_pipeline_jobs(
    limit: int = 20,
    include_partial_failed: bool = True,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_service import DocumentService

    statuses = ["failed", "partial_failed"] if include_partial_failed else ["failed"]
    rows = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id, Document.status.in_(statuses))
        .order_by(Document.updated_at.desc())
        .limit(max(limit, 1))
    )
    documents = rows.scalars().all()
    service = DocumentService(db, get_minio_client())
    queued = []
    for item in documents:
        result = await service.enqueue_retry(doc_id=item.id, user=current_user)
        queued.append(result)
    return {"queued_count": len(queued), "queued": queued}


@router.get("/pipeline/failure-summary")
async def get_pipeline_failure_summary(
    limit: int = 20,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id, Document.status.in_(["failed", "partial_failed"]))
        .order_by(Document.updated_at.desc())
        .limit(500)
    )
    documents = rows.scalars().all()
    grouped: dict[str, dict] = {}
    for item in documents:
        signature = _error_signature(item.error_message)
        slot = grouped.setdefault(
            signature,
            {
                "signature": signature,
                "count": 0,
                "latest_at": item.updated_at.isoformat(),
                "example_error": item.error_message or "",
                "status_breakdown": {"failed": 0, "partial_failed": 0},
                "doc_ids": [],
            },
        )
        slot["count"] += 1
        slot["latest_at"] = max(slot["latest_at"], item.updated_at.isoformat())
        slot["example_error"] = slot["example_error"] or (item.error_message or "")
        slot["status_breakdown"][item.status] = slot["status_breakdown"].get(item.status, 0) + 1
        if len(slot["doc_ids"]) < 10:
            slot["doc_ids"].append(item.id)

    items = sorted(grouped.values(), key=lambda x: (x["count"], x["latest_at"]), reverse=True)[: max(limit, 1)]
    return {"items": items, "total": len(grouped), "source_count": len(documents)}


@router.post("/pipeline/retry-by-signature")
async def retry_pipeline_jobs_by_signature(
    signature: str,
    limit: int = 20,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_service import DocumentService

    rows = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id, Document.status.in_(["failed", "partial_failed"]))
        .order_by(Document.updated_at.desc())
        .limit(500)
    )
    documents = rows.scalars().all()
    matched = [item for item in documents if _error_signature(item.error_message) == signature][: max(limit, 1)]
    service = DocumentService(db, get_minio_client())
    queued = []
    for item in matched:
        queued.append(await service.enqueue_retry(doc_id=item.id, user=current_user))
    return {"signature": signature, "matched_count": len(matched), "queued_count": len(queued), "queued": queued}


@router.get("/security/events")
async def get_security_events(
    limit: int = 50,
    offset: int = 0,
    severity: str | None = None,
    action: str | None = None,
    result: str | None = None,
    from_time: str | None = Query(default=None, alias="from"),
    to_time: str | None = Query(default=None, alias="to"),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService

    def parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except ValueError:
            return None

    data = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=limit,
        offset=offset,
        severity=severity,
        action=action,
        result=result,
        from_time=parse_iso(from_time),
        to_time=parse_iso(to_time),
    )
    return data


@router.get("/security/alerts")
async def get_security_alerts(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService

    return await SecurityAuditService(get_redis(), db).list_alerts(current_user.tenant_id, limit=limit, offset=offset)


@router.post("/security/watermark/trace")
async def trace_watermark(
    text: str | None = None,
    fingerprint: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.dlp_forensics_service import DLPForensicsService

    service = DLPForensicsService(get_redis(), db)
    if fingerprint:
        result = await service.trace_by_fingerprint(tenant_id=current_user.tenant_id, fingerprint=fingerprint)
        return {"result": result, "found": bool(result), "mode": "fingerprint"}
    if text:
        result = await service.trace_from_text(tenant_id=current_user.tenant_id, text=text)
        return {"result": result, "found": bool(result and result.get("found", True)), "mode": "text"}
    return {"result": None, "found": False, "mode": "none", "message": "请提供 text 或 fingerprint"}


@router.get("/system/backends")
async def get_backend_status(current_user: User = Depends(require_role("ADMIN"))):
    from app.retrieval.es_client import ESClient
    from app.retrieval.milvus_client import MilvusClient
    from app.retrieval.neo4j_client import Neo4jClient
    from app.security.pii_masker import PIIMasker
    from app.services.llm_service import LLMService
    from app.security.file_scanner import FileScanner
    from app.services.guardrails_service import GuardrailsService
    from app.config import settings

    async def run_sync_health(name: str, fn, timeout: float = 2.5):
        try:
            result = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
            if isinstance(result, dict):
                result.setdefault("available", True)
            return name, result
        except Exception as exc:  # noqa: BLE001
            return name, {"available": False, "status": "degraded", "error": str(exc)}

    async def run_async_health(name: str, coro, timeout: float = 2.5):
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            if isinstance(result, dict):
                result.setdefault("available", True)
            return name, result
        except Exception as exc:  # noqa: BLE001
            return name, {"available": False, "status": "degraded", "error": str(exc)}

    def neo4j_health():
        client = Neo4jClient()
        try:
            return client.health()
        finally:
            client.close()

    checks = await asyncio.gather(
        run_sync_health("elasticsearch", lambda: ESClient().health()),
        run_sync_health("milvus", lambda: MilvusClient().health()),
        run_sync_health("neo4j", neo4j_health),
        run_sync_health("clamav", lambda: FileScanner().health()),
        run_async_health("llm", LLMService().health()),
        run_async_health("guardrails", GuardrailsService().health()),
    )
    payload = {name: result for name, result in checks}
    payload["redis"] = {"available": get_redis() is not None}
    payload["pii"] = {
        "available": bool(settings.pii_masking_enabled),
        "presidio_enabled": bool(settings.pii_presidio_enabled),
        "mode": "presidio_patterns" if PIIMasker()._recognizers else "local_regex",
    }
    payload["runtime"] = {"mode": "v2_only"}
    return payload


@router.get("/system/retrieval-metrics")
async def get_retrieval_metrics(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.retrieval_observability_service import RetrievalObservabilityService

    return await RetrievalObservabilityService(get_redis()).summary(current_user.tenant_id)


@router.get("/system/readiness")
async def get_platform_readiness(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.platform_readiness_service import PlatformReadinessService

    return await PlatformReadinessService(db, get_redis()).evaluate(current_user.tenant_id)


@router.get("/system/gap-report")
async def get_delivery_gap_report(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.delivery_gap_service import DeliveryGapService

    return await DeliveryGapService().build_report()


@router.get("/system/security-policy")
async def get_security_policy(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.security_policy_service import SecurityPolicyService

    return SecurityPolicyService().evaluate()


@router.get("/runtime/tasks")
async def get_runtime_tasks(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.task_store import TaskStore
    from app.config import settings

    store = TaskStore(get_redis(), retention_seconds=settings.runtime_task_retention_seconds)
    tasks = await store.list_tasks(current_user.tenant_id, limit=max(limit, 1), offset=max(offset, 0))
    return {"items": tasks, "total": len(tasks), "limit": max(limit, 1), "offset": max(offset, 0)}


@router.get("/runtime/metrics")
async def get_runtime_metrics_v2(
    limit: int = 200,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.engine import AgentRuntime

    runtime = AgentRuntime(get_redis())
    rows = await runtime.list_metrics(current_user.tenant_id, limit=max(limit, 1))
    redis_client = get_redis()
    counters = await redis_client.hgetall(f"runtime:counters:{current_user.tenant_id}") if redis_client is not None else {}
    if not rows:
        return {
            "items": [],
            "summary": {
                "count": 0,
                "ttft_ms_p95": 0,
                "completion_ms_p95": 0,
                "fallback_rate": 0.0,
                "deny_rate": 0.0,
                "avg_retries": 0.0,
                "avg_tool_calls": 0.0,
                "sse_disconnects": int(counters.get("sse_disconnects", 0) or 0),
            },
        }

    ttft = sorted(int(item.get("ttft_ms", 0) or 0) for item in rows)
    completion = sorted(int(item.get("completion_ms", 0) or 0) for item in rows)
    fallback_sum = sum(int(item.get("fallback_rate", 0) or 0) for item in rows)
    deny_sum = sum(int(item.get("deny_rate", 0) or 0) for item in rows)
    retries_sum = sum(int(item.get("retries", 0) or 0) for item in rows)
    tool_calls_sum = sum(int(item.get("tool_calls", 0) or 0) for item in rows)
    idx = max(int(len(rows) * 0.95) - 1, 0)
    summary = {
        "count": len(rows),
        "ttft_ms_p95": ttft[idx],
        "completion_ms_p95": completion[idx],
        "fallback_rate": round(fallback_sum / max(len(rows), 1), 4),
        "deny_rate": round(deny_sum / max(len(rows), 1), 4),
        "avg_retries": round(retries_sum / max(len(rows), 1), 4),
        "avg_tool_calls": round(tool_calls_sum / max(len(rows), 1), 4),
        "sse_disconnects": int(counters.get("sse_disconnects", 0) or 0),
    }
    return {"items": rows, "summary": summary}


@router.get("/runtime/tool-decisions")
async def get_runtime_tool_decisions(
    limit: int = 100,
    offset: int = 0,
    source: str = "merged",
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.runtime.permission_gate import PermissionGate
    from app.services.security_audit_service import SecurityAuditService

    gate = PermissionGate(get_redis())
    runtime_items = await gate.list_decisions(current_user.tenant_id, limit=max(limit, 1), offset=max(offset, 0))

    if source == "redis":
        return {"items": runtime_items, "total": len(runtime_items), "limit": max(limit, 1), "offset": max(offset, 0), "source": "redis"}

    audit_payload = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=max(limit, 1),
        offset=max(offset, 0),
        action="runtime_tool_decision",
    )
    audit_items = []
    for item in audit_payload.get("events", []):
        metadata = item.get("metadata") or {}
        audit_items.append(
            {
                "decision": item.get("result"),
                "reason": metadata.get("reason") or item.get("message"),
                "source": metadata.get("source") or "security_audit",
                "tool_name": metadata.get("tool_name") or item.get("target"),
                "user_id": item.get("user_id"),
                "tenant_id": item.get("tenant_id"),
                "trace_id": item.get("trace_id"),
                "created_at": item.get("timestamp"),
                "channel": "security_audit",
            }
        )

    if source == "audit":
        return {"items": audit_items, "total": len(audit_items), "limit": max(limit, 1), "offset": max(offset, 0), "source": "audit"}

    merged = runtime_items + audit_items
    merged.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    merged = merged[: max(limit, 1)]
    return {"items": merged, "total": len(merged), "limit": max(limit, 1), "offset": max(offset, 0), "source": "merged"}


@router.get("/runtime/tool-decisions/summary")
async def get_runtime_tool_decisions_summary(
    limit: int = 1000,
    since_hours: int = 24,
    decision: str | None = None,
    tool_name: str | None = None,
    reason: str | None = None,
    source: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.runtime.permission_gate import PermissionGate
    from app.services.security_audit_service import SecurityAuditService

    gate = PermissionGate(get_redis())
    runtime_items = await gate.list_decisions(current_user.tenant_id, limit=max(limit, 1), offset=0)
    audit_payload = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=max(limit, 1),
        offset=0,
        action="runtime_tool_decision",
    )

    items: list[dict] = []
    items.extend(runtime_items)
    for item in audit_payload.get("events", []):
        metadata = item.get("metadata") or {}
        items.append(
            {
                "decision": item.get("result"),
                "reason": metadata.get("reason") or item.get("message"),
                "source": metadata.get("source") or "security_audit",
                "tool_name": metadata.get("tool_name") or item.get("target"),
                "created_at": item.get("timestamp"),
            }
        )

    def parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except ValueError:
            return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since_dt = now
    if since_hours > 0:
        since_dt = now - timedelta(hours=since_hours)

    decision_filter = (decision or "").strip().lower()
    tool_filter = (tool_name or "").strip().lower()
    reason_filter = (reason or "").strip().lower()
    source_filter = (source or "").strip().lower()

    filtered_items = []
    for item in items:
        created_at = parse_iso(str(item.get("created_at") or ""))
        if since_hours > 0 and created_at and created_at < since_dt:
            continue
        item_decision = str(item.get("decision") or "unknown").lower()
        item_tool = str(item.get("tool_name") or "unknown").lower()
        item_reason = str(item.get("reason") or "unknown").lower()
        item_source = str(item.get("source") or "unknown").lower()
        if decision_filter and item_decision != decision_filter:
            continue
        if tool_filter and tool_filter not in item_tool:
            continue
        if reason_filter and reason_filter not in item_reason:
            continue
        if source_filter and item_source != source_filter:
            continue
        filtered_items.append(item)

    decision_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    tool_decision_matrix: dict[str, dict[str, int]] = {}
    reason_decision_matrix: dict[str, dict[str, int]] = {}
    source_counts: dict[str, int] = {}
    trend_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"allow": 0, "ask": 0, "deny": 0, "unknown": 0})
    for item in filtered_items:
        decision = str(item.get("decision") or "unknown")
        tool_name = str(item.get("tool_name") or "unknown")
        reason = str(item.get("reason") or "unknown")
        source = str(item.get("source") or "unknown")
        created_at = parse_iso(str(item.get("created_at") or "")) or now
        bucket = created_at.replace(minute=0, second=0, microsecond=0).isoformat()
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        tool_bucket = tool_decision_matrix.setdefault(tool_name, {})
        tool_bucket[decision] = tool_bucket.get(decision, 0) + 1
        reason_bucket = reason_decision_matrix.setdefault(reason, {})
        reason_bucket[decision] = reason_bucket.get(decision, 0) + 1
        trend_buckets[bucket][decision if decision in {"allow", "ask", "deny"} else "unknown"] += 1

    top_tools = sorted(tool_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    top_reasons = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    matrix_tools = []
    for tool_name, _ in top_tools:
        row = {"tool_name": tool_name}
        row.update(tool_decision_matrix.get(tool_name, {}))
        matrix_tools.append(row)

    matrix_reasons = []
    for reason, _ in top_reasons:
        row = {"reason": reason}
        row.update(reason_decision_matrix.get(reason, {}))
        matrix_reasons.append(row)

    return {
        "total": len(filtered_items),
        "window_hours": since_hours,
        "applied_filters": {
            "decision": decision_filter or None,
            "tool_name": tool_filter or None,
            "reason": reason_filter or None,
            "source": source_filter or None,
        },
        "decision_counts": decision_counts,
        "source_counts": source_counts,
        "top_tools": [{"tool_name": name, "count": count} for name, count in top_tools],
        "top_reasons": [{"reason": name, "count": count} for name, count in top_reasons],
        "matrix_by_tool": matrix_tools,
        "matrix_by_reason": matrix_reasons,
        "trend_by_hour": [{"hour": hour, **counts} for hour, counts in sorted(trend_buckets.items())],
    }


@router.post("/runtime/replay")
async def replay_runtime_trace(
    trace_id: str,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.engine import AgentRuntime

    runtime = AgentRuntime(get_redis())
    events = await runtime.replay(trace_id)
    events = [item for item in events if item.get("tenant_id") == current_user.tenant_id]
    return {"trace_id": trace_id, "events": events, "count": len(events)}


@router.get("/runtime/checkpoints")
async def list_runtime_checkpoints(
    session_id: str,
    limit: int = 50,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.runtime.checkpoint_store import RuntimeCheckpointStore

    store = RuntimeCheckpointStore(db)
    rows = await store.list_for_session(session_id, limit=max(limit, 1))
    items = []
    for row in rows:
        if row.tenant_id != current_user.tenant_id:
            continue
        items.append(
            {
                "id": row.id,
                "session_id": row.session_id,
                "trace_id": row.trace_id,
                "tenant_id": row.tenant_id,
                "node_name": row.node_name,
                "iteration": row.iteration,
                "payload_json": row.payload_json,
                "created_at": row.created_at.isoformat(),
            }
        )
    return {"items": items, "count": len(items), "session_id": session_id}


@router.get("/runtime/checkpoints/summary")
async def list_runtime_checkpoint_summary(
    limit: int = 50,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.runtime_checkpoint_service import RuntimeCheckpointService

    items = await RuntimeCheckpointService(db).summarize_sessions(current_user.tenant_id, limit=max(limit, 1))
    return {"items": items, "count": len(items), "limit": max(limit, 1)}


@router.get("/system/retrieval-integrity")
async def get_retrieval_integrity(
    sample_size: int = 12,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.retrieval_integrity_service import RetrievalIntegrityService

    return await RetrievalIntegrityService(db).evaluate(current_user.tenant_id, sample_size=max(sample_size, 1))


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
    from app.evaluation.tasks import run_evaluation_job

    task = run_evaluation_job.apply_async(
        args=(current_user.tenant_id, max(sample_limit, 1), current_user.id),
        queue=settings.celery_maintenance_queue,
    )
    redis_client = get_redis()
    if redis_client is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        payload = {
            "task_id": task.id,
            "type": "evaluation",
            "status": "pending",
            "description": f"评估任务: tenant={current_user.tenant_id}",
            "tool_use_id": None,
            "start_time": now,
            "end_time": None,
            "output_offset": 0,
            "retries": 0,
            "notified": False,
            "trace_id": task.id,
            "tenant_id": current_user.tenant_id,
            "session_id": None,
            "stage": "queued",
            "error": None,
            "updated_at": now,
        }
        await redis_client.set(f"runtime:task:{task.id}", json.dumps(payload, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
        await redis_client.zadd(f"runtime:tasks:{current_user.tenant_id}", {task.id: datetime.now(timezone.utc).timestamp()})
        await redis_client.expire(f"runtime:tasks:{current_user.tenant_id}", settings.runtime_task_retention_seconds)
    return {"task_id": task.id, "status": "pending", "tenant_id": current_user.tenant_id, "sample_limit": max(sample_limit, 1)}


@router.get("/evaluation/tasks/{task_id}")
async def get_evaluation_task(task_id: str, current_user: User = Depends(require_role("ADMIN"))):
    from dataclasses import asdict

    from app.agent.runtime.task_store import TERMINAL_STATUSES
    from app.agent.runtime.task_store import TaskStore
    from celery.result import AsyncResult

    from celery_app import celery

    store = TaskStore(get_redis(), retention_seconds=settings.runtime_task_retention_seconds)
    record = await store.get(task_id)
    if record is None or record.tenant_id != current_user.tenant_id or record.type != "evaluation":
        return {"exists": False, "task_id": task_id}
    result = AsyncResult(task_id, app=celery)
    raw = result.result if result.ready() else None
    if result.ready() and record.status not in TERMINAL_STATUSES:
        if isinstance(raw, dict) and raw.get("ok", True):
            await store.complete(task_id)
        elif isinstance(raw, dict):
            await store.fail(task_id, str(raw.get("error") or "evaluation_failed"))
        else:
            await store.fail(task_id, str(raw))
        record = await store.get(task_id) or record
    payload = {"exists": True, "item": asdict(record), "celery_state": result.state}
    if result.ready():
        if isinstance(raw, dict):
            payload["result"] = raw
        else:
            payload["result"] = {"value": str(raw)}
    return payload


@router.get("/evaluation/latest")
async def get_latest_evaluation(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(None, get_redis(), reports_dir=REPORTS_DIR).latest(current_user.tenant_id)


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
