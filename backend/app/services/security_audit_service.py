"""Security audit event service backed by PostgreSQL and Redis fallback."""

from __future__ import annotations

import json
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
                try:
                    metadata = json.loads(item.metadata_json) if item.metadata_json else {}
                except json.JSONDecodeError:
                    metadata = {}
                events.append(
                    {
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
                )
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
