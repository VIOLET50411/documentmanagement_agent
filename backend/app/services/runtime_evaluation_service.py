"""Runtime evaluation metrics service for non-LLM stage."""

from __future__ import annotations

import csv
import io
import json
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.document import Document
from app.models.db.security_audit import SecurityAuditEvent
from app.models.db.session import ChatMessage, ChatSession


class RuntimeEvaluationService:
    def __init__(self, db: AsyncSession, redis_client):
        self.db = db
        self.redis = redis_client

    async def get_metrics(self, tenant_id: str, *, persist_history: bool = True) -> dict:
        assistant_total = int(
            await self.db.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(ChatSession.tenant_id == tenant_id, ChatMessage.role == "assistant")
            )
            or 0
        )
        assistant_with_citations = int(
            await self.db.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(
                    ChatSession.tenant_id == tenant_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.citations_json.is_not(None),
                    ChatMessage.citations_json != "[]",
                    ChatMessage.citations_json != "",
                )
            )
            or 0
        )
        user_queries = int(
            await self.db.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(ChatSession.tenant_id == tenant_id, ChatMessage.role == "user")
            )
            or 0
        )
        cache_hits = int(
            await self.db.scalar(
                select(func.count())
                .select_from(ChatMessage)
                .join(ChatSession, ChatSession.id == ChatMessage.session_id)
                .where(ChatSession.tenant_id == tenant_id, ChatMessage.role == "assistant", ChatMessage.agent_used == "cache")
            )
            or 0
        )

        ingestion_terminal = int(
            await self.db.scalar(
                select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id, Document.status.in_(["ready", "partial_failed", "failed"]))
            )
            or 0
        )
        ingestion_success = int(
            await self.db.scalar(
                select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id, Document.status.in_(["ready", "partial_failed"]))
            )
            or 0
        )

        access_violations = int(
            await self.db.scalar(
                select(func.count())
                .select_from(SecurityAuditEvent)
                .where(
                    SecurityAuditEvent.tenant_id == tenant_id,
                    SecurityAuditEvent.action.in_(["access_violation", "rbac_violation", "tenant_isolation_violation"]),
                )
            )
            or 0
        )

        sse_key = f"metrics:sse_first_event_ms:{tenant_id}"
        sse_values: list[int] = []
        if self.redis is not None:
            rows = await self.redis.lrange(sse_key, 0, 999)
            for item in rows:
                try:
                    sse_values.append(int(item))
                except (TypeError, ValueError):
                    continue

        metrics = {
            "retrieval_hit_rate": _safe_div(assistant_with_citations, user_queries),
            "citation_coverage": _safe_div(assistant_with_citations, assistant_total),
            "access_control_correctness": 1.0 if access_violations == 0 else 0.0,
            "cache_hit_rate": _safe_div(cache_hits, assistant_total),
            "ingestion_success_rate": _safe_div(ingestion_success, ingestion_terminal),
            "sse_first_event_latency_p95_ms": _p95(sse_values),
            "sse_first_event_latency_avg_ms": round(mean(sse_values), 2) if sse_values else None,
            "counts": {
                "assistant_total": assistant_total,
                "assistant_with_citations": assistant_with_citations,
                "user_queries": user_queries,
                "cache_hits": cache_hits,
                "ingestion_terminal": ingestion_terminal,
                "ingestion_success": ingestion_success,
                "access_violations": access_violations,
                "sse_latency_samples": len(sse_values),
            },
        }
        if persist_history and self.redis is not None:
            history_key = f"metrics:runtime_eval:history:{tenant_id}"
            await self.redis.lpush(history_key, json.dumps(metrics, ensure_ascii=False))
            await self.redis.ltrim(history_key, 0, 199)
            await self.redis.expire(history_key, 30 * 24 * 3600)
        return metrics

    async def get_history(self, tenant_id: str, limit: int = 50) -> dict:
        if self.redis is None:
            return {"items": [], "total": 0}
        history_key = f"metrics:runtime_eval:history:{tenant_id}"
        rows = await self.redis.lrange(history_key, 0, max(limit - 1, 0))
        items = []
        for row in rows:
            try:
                items.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        total = await self.redis.llen(history_key)
        return {"items": items, "total": int(total or 0)}

    async def export_csv(self, tenant_id: str, limit: int = 100) -> str:
        history = await self.get_history(tenant_id, limit=limit)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "retrieval_hit_rate",
                "citation_coverage",
                "access_control_correctness",
                "cache_hit_rate",
                "ingestion_success_rate",
                "sse_first_event_latency_p95_ms",
                "sse_first_event_latency_avg_ms",
                "assistant_total",
                "user_queries",
                "cache_hits",
            ]
        )
        for item in history["items"]:
            counts = item.get("counts", {})
            writer.writerow(
                [
                    item.get("retrieval_hit_rate"),
                    item.get("citation_coverage"),
                    item.get("access_control_correctness"),
                    item.get("cache_hit_rate"),
                    item.get("ingestion_success_rate"),
                    item.get("sse_first_event_latency_p95_ms"),
                    item.get("sse_first_event_latency_avg_ms"),
                    counts.get("assistant_total"),
                    counts.get("user_queries"),
                    counts.get("cache_hits"),
                ]
            )
        return output.getvalue()


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * (len(ordered) - 1))))
    return ordered[index]
