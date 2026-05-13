"""Admin sub-router: system health, runtime tasks/metrics, retrieval."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.db.user import User
from app.observability.metrics import metrics_registry

from app.api.v1.admin._helpers import (
    _parse_runtime_iso, _normalize_tool_decision_item,
    _merge_tool_decision_items, _admin_cache_key, _load_admin_cached_payload,
)

router = APIRouter()
_retrieval_debug_searcher = None

@router.get("/system/retrieval-metrics")
async def get_retrieval_metrics(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.retrieval_observability_service import RetrievalObservabilityService

    return await RetrievalObservabilityService(get_redis()).summary(current_user.tenant_id)


@router.get("/system/request-metrics")
async def get_request_metrics(
    limit: int = 10,
    current_user: User = Depends(require_role("ADMIN")),
):
    return {"items": metrics_registry.snapshot_request_metrics(limit=max(limit, 1)), "limit": max(limit, 1)}


@router.get("/system/retrieval-debug")
async def get_retrieval_debug(
    q: str,
    top_k: int = 8,
    search_type: str = "hybrid",
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.nodes.query_rewriter import query_rewriter
    from app.retrieval.hybrid_searcher import HybridSearcher

    global _retrieval_debug_searcher
    normalized_query = (q or "").strip()
    if not normalized_query:
        return {
            "query": q,
            "rewritten_query": "",
            "rewrite_source": "empty",
            "search_type": search_type,
            "original_results": [],
            "original_total": 0,
            "results": [],
            "total": 0,
        }

    rewrite_state = await query_rewriter({"query": normalized_query, "messages": [{"role": "user", "content": normalized_query}]})
    rewritten_query = str(rewrite_state.get("rewritten_query") or normalized_query).strip()
    rewrite_source = str(rewrite_state.get("rewrite_source") or "passthrough")

    if _retrieval_debug_searcher is None:
        _retrieval_debug_searcher = HybridSearcher()

    original_results = await _retrieval_debug_searcher.search(
        query=normalized_query,
        user=current_user,
        top_k=max(min(top_k, 20), 1),
        search_type=search_type,
        db=db,
    )
    results = await _retrieval_debug_searcher.search(
        query=rewritten_query,
        user=current_user,
        top_k=max(min(top_k, 20), 1),
        search_type=search_type,
        db=db,
    )
    return {
        "query": normalized_query,
        "rewritten_query": rewritten_query,
        "rewrite_source": rewrite_source,
        "search_type": search_type,
        "original_results": original_results,
        "original_total": len(original_results),
        "results": results,
        "total": len(results),
    }


@router.get("/system/readiness")
async def get_platform_readiness(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.platform_readiness_service import PlatformReadinessService

    return await _load_admin_cached_payload(
        _admin_cache_key(current_user.tenant_id, "platform_readiness"),
        lambda: PlatformReadinessService(db, get_redis()).evaluate(current_user.tenant_id),
    )


@router.get("/system/gap-report")
async def get_delivery_gap_report(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.delivery_gap_service import DeliveryGapService
    from app.services.push_notification_service import PushNotificationService

    redis_client = get_redis()
    report = await DeliveryGapService(db, redis_client).build_report(current_user.tenant_id)
    report["push_runtime_status"] = await PushNotificationService(db, redis_client).get_health_summary(
        tenant_id=current_user.tenant_id
    )
    return report


@router.get("/system/security-policy")
async def get_security_policy(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.security_policy_service import SecurityPolicyService

    return SecurityPolicyService().evaluate()


@router.get("/system/mobile-auth")
async def get_mobile_auth_status(
    request: Request,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mobile_oauth_service import MobileOAuthService

    issuer = str(request.base_url).rstrip("/")
    return {"tenant_id": current_user.tenant_id, **MobileOAuthService(db).status(issuer)}


@router.get("/system/push-notifications")
async def get_push_notification_status(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.push_notification_service import PushNotificationService

    return await PushNotificationService(db, get_redis()).get_health_summary(tenant_id=current_user.tenant_id)


@router.get("/runtime/tasks")
async def get_runtime_tasks(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.task_store import TaskStore
    from app.config import settings

    store = TaskStore(get_redis(), retention_seconds=settings.runtime_task_retention_seconds)
    all_tasks = await store.list(current_user.tenant_id)
    # Sort tasks by start_time or updated_at descending
    all_tasks.sort(key=lambda t: t.updated_at or t.start_time or "", reverse=True)
    limit_val = max(limit, 1)
    offset_val = max(offset, 0)
    tasks = all_tasks[offset_val : offset_val + limit_val]
    return {"items": tasks, "total": len(all_tasks), "limit": limit_val, "offset": offset_val}


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
        rows = [_normalize_tool_decision_item(item, source_hint="runtime") for item in runtime_items]
        return {"items": rows, "total": len(rows), "limit": max(limit, 1), "offset": max(offset, 0), "source": "redis"}

    audit_payload = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=max(limit, 1),
        offset=max(offset, 0),
        action="runtime_tool_decision",
    )
    audit_items = [_normalize_tool_decision_item(item, source_hint="security_audit") for item in audit_payload.get("events", [])]

    if source == "audit":
        return {"items": audit_items, "total": len(audit_items), "limit": max(limit, 1), "offset": max(offset, 0), "source": "audit"}

    merged = _merge_tool_decision_items(runtime_items, audit_items)
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

    audit_items = [_normalize_tool_decision_item(item, source_hint="security_audit") for item in audit_payload.get("events", [])]
    items = _merge_tool_decision_items(runtime_items, audit_items)

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
        created_at = _parse_runtime_iso(str(item.get("created_at") or ""))
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
        created_at = _parse_runtime_iso(str(item.get("created_at") or "")) or now
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

    items = await _load_admin_cached_payload(
        _admin_cache_key(current_user.tenant_id, "runtime_checkpoint_summary", max(limit, 1)),
        lambda: _load_runtime_checkpoint_summary(db, current_user.tenant_id, max(limit, 1)),
        ttl_seconds=10,
    )
    return {"items": items.get("items", []), "count": items.get("count", 0), "limit": max(limit, 1)}


async def _load_runtime_checkpoint_summary(db: AsyncSession, tenant_id: str, limit: int) -> dict:
    from app.services.runtime_checkpoint_service import RuntimeCheckpointService

    items = await RuntimeCheckpointService(db).summarize_sessions(tenant_id, limit=limit)
    return {"items": items, "count": len(items), "limit": max(limit, 1)}


@router.get("/system/retrieval-integrity")
async def get_retrieval_integrity(
    sample_size: int = 12,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.retrieval_integrity_service import RetrievalIntegrityService

    normalized_size = max(sample_size, 1)
    return await _load_admin_cached_payload(
        _admin_cache_key(current_user.tenant_id, "retrieval_integrity", normalized_size),
        lambda: RetrievalIntegrityService(db).evaluate(current_user.tenant_id, sample_size=normalized_size),
    )
