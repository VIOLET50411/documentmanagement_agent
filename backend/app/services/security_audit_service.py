"""Security audit event service backed by PostgreSQL and Redis fallback."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import and_, desc, func, select

from app.models.db.security_audit import SecurityAuditEvent


class SecurityAuditService:
    """Record and retrieve lightweight tenant-scoped security audit events."""

    def __init__(self, redis_client, db=None):
        self.redis = redis_client
        self.db = db

    async def log_event(
        self,
        tenant_id: str,
        event_type: str,
        severity: str,
        message: str,
        *,
        user_id: str | None = None,
        target: str | None = None,
        result: str = "ok",
        trace_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        payload = {
            "tenant_id": tenant_id,
            "actor_id": user_id,
            "event_type": event_type,
            "action": event_type,
            "target": target,
            "result": result,
            "severity": severity,
            "message": message,
            "user_id": user_id,
            "trace_id": trace_id,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.db is not None:
            event = SecurityAuditEvent(
                tenant_id=tenant_id,
                actor_id=user_id,
                action=event_type,
                target=target,
                result=result,
                severity=severity,
                message=message,
                trace_id=trace_id,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            )
            self.db.add(event)
            await self.db.flush()

        if self.redis is not None:
            key = f"security_audit:{tenant_id}"
            await self.redis.lpush(key, json.dumps(payload, ensure_ascii=False))
            await self.redis.ltrim(key, 0, 199)
            await self.redis.expire(key, 14 * 24 * 3600)
            if severity in {"high", "critical"} or result in {"blocked", "error", "warning"}:
                await self.redis.lpush(f"security_alerts:{tenant_id}", json.dumps(payload, ensure_ascii=False))
                await self.redis.ltrim(f"security_alerts:{tenant_id}", 0, 499)
                await self.redis.expire(f"security_alerts:{tenant_id}", 14 * 24 * 3600)

    async def list_events(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        severity: str | None = None,
        action: str | None = None,
        result: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> dict:
        filters = [SecurityAuditEvent.tenant_id == tenant_id]
        if severity:
            filters.append(SecurityAuditEvent.severity == severity)
        if action:
            filters.append(SecurityAuditEvent.action == action)
        if result:
            filters.append(SecurityAuditEvent.result == result)
        if from_time:
            filters.append(SecurityAuditEvent.created_at >= from_time)
        if to_time:
            filters.append(SecurityAuditEvent.created_at <= to_time)

        events: list[dict] = []

        if self.db is not None:
            where_clause = and_(*filters)
            total = await self.db.scalar(select(func.count()).select_from(SecurityAuditEvent).where(where_clause))
            rows = await self.db.execute(
                select(SecurityAuditEvent)
                .where(where_clause)
                .order_by(desc(SecurityAuditEvent.created_at))
                .limit(max(limit, 1))
                .offset(max(offset, 0))
            )
            for item in rows.scalars().all():
                events.append(self._serialize_event(item))
            return {"events": events, "total": int(total or 0), "source": "postgres"}

        if self.redis is None:
            return {"events": [], "total": 0, "source": "none"}

        key = f"security_audit:{tenant_id}"
        rows = await self.redis.lrange(key, max(offset, 0), max(offset, 0) + max(limit - 1, 0))
        for row in rows:
            try:
                events.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        total = await self.redis.llen(key)
        return {"events": events, "total": int(total or 0), "source": "redis"}

    async def list_alerts(self, tenant_id: str, *, limit: int = 50, offset: int = 0) -> dict:
        if self.db is not None:
            alert_filter = and_(
                SecurityAuditEvent.tenant_id == tenant_id,
                (
                    SecurityAuditEvent.severity.in_(["high", "critical"])
                    | SecurityAuditEvent.result.in_(["blocked", "error", "warning"])
                ),
            )
            total = await self.db.scalar(select(func.count()).select_from(SecurityAuditEvent).where(alert_filter))
            rows = await self.db.execute(
                select(SecurityAuditEvent)
                .where(alert_filter)
                .order_by(desc(SecurityAuditEvent.created_at))
                .limit(max(limit, 1))
                .offset(max(offset, 0))
            )
            alerts = [self._serialize_event(item) for item in rows.scalars().all()]
            return {"alerts": alerts, "total": int(total or 0), "source": "postgres"}

        if self.redis is None:
            return {"alerts": [], "total": 0, "source": "none"}
        key = f"security_alerts:{tenant_id}"
        rows = await self.redis.lrange(key, max(offset, 0), max(offset, 0) + max(limit - 1, 0))
        alerts: list[dict] = []
        for row in rows:
            try:
                alerts.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        total = await self.redis.llen(key)
        return {"alerts": alerts, "total": int(total or 0), "source": "redis"}

    async def summarize_events(
        self,
        tenant_id: str,
        *,
        limit: int = 1000,
        severity: str | None = None,
        action: str | None = None,
        result: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> dict:
        payload = await self.list_events(
            tenant_id,
            limit=max(limit, 1),
            offset=0,
            severity=severity,
            action=action,
            result=result,
            from_time=from_time,
            to_time=to_time,
        )
        events = payload.get("events", [])
        severity_counts: dict[str, int] = {}
        action_counts: dict[str, int] = {}
        result_counts: dict[str, int] = {}
        hourly_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "warning": 0, "blocked": 0, "error": 0, "other": 0})

        for item in events:
            item_severity = str(item.get("severity") or "unknown")
            item_action = str(item.get("action") or item.get("event_type") or "unknown")
            item_result = str(item.get("result") or "unknown")
            severity_counts[item_severity] = severity_counts.get(item_severity, 0) + 1
            action_counts[item_action] = action_counts.get(item_action, 0) + 1
            result_counts[item_result] = result_counts.get(item_result, 0) + 1

            bucket_key = self._bucket_hour(item.get("timestamp"))
            normalized_result = item_result if item_result in {"ok", "warning", "blocked", "error"} else "other"
            hourly_buckets[bucket_key][normalized_result] += 1

        top_actions = sorted(action_counts.items(), key=lambda item: item[1], reverse=True)[:20]
        top_severities = sorted(severity_counts.items(), key=lambda item: item[1], reverse=True)[:20]
        top_results = sorted(result_counts.items(), key=lambda item: item[1], reverse=True)[:20]
        return {
            "total": len(events),
            "source": payload.get("source"),
            "severity_counts": severity_counts,
            "action_counts": action_counts,
            "result_counts": result_counts,
            "top_actions": [{"action": name, "count": count} for name, count in top_actions],
            "top_severities": [{"severity": name, "count": count} for name, count in top_severities],
            "top_results": [{"result": name, "count": count} for name, count in top_results],
            "trend_by_hour": [{"hour": hour, **counts} for hour, counts in sorted(hourly_buckets.items())],
        }

    def _serialize_event(self, item: SecurityAuditEvent) -> dict:
        try:
            metadata = json.loads(item.metadata_json) if item.metadata_json else {}
        except json.JSONDecodeError:
            metadata = {}
        return {
            "tenant_id": item.tenant_id,
            "event_type": item.action,
            "action": item.action,
            "target": item.target,
            "result": item.result,
            "severity": item.severity,
            "message": item.message,
            "user_id": item.actor_id,
            "actor_id": item.actor_id,
            "trace_id": item.trace_id,
            "metadata": metadata,
            "timestamp": item.created_at.replace(tzinfo=timezone.utc).isoformat(),
        }

    def _bucket_hour(self, timestamp: str | None) -> str:
        if not timestamp:
            return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
