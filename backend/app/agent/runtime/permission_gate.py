"""Permission gate for all runtime tool calls."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.agent.runtime.tool_registry import ToolSpec


@dataclass(slots=True)
class PermissionDecision:
    decision: str
    reason: str
    source: str
    tool_name: str
    user_id: str | None
    tenant_id: str
    trace_id: str | None
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class PermissionGate:
    """Evaluate tool permission with RBAC + tenant safety defaults."""

    def __init__(self, redis_client=None):
        self.redis = redis_client

    async def evaluate(self, *, tool: ToolSpec | None, user_context: dict, trace_id: str | None = None) -> PermissionDecision:
        tenant_id = str(user_context.get("tenant_id") or "default")
        user_id = str(user_context.get("user_id")) if user_context.get("user_id") is not None else None
        role = str(user_context.get("role") or "VIEWER").upper()
        tool_name = tool.name if tool else "unknown"

        if tool is None:
            decision = PermissionDecision(
                decision="deny",
                reason="tool_not_registered",
                source="registry",
                tool_name=tool_name,
                user_id=user_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            )
            await self._log(decision)
            return decision

        if not tool.enabled:
            decision = PermissionDecision(
                decision="deny",
                reason="tool_disabled",
                source="tool_spec",
                tool_name=tool.name,
                user_id=user_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            )
            await self._log(decision)
            return decision

        if tool.risk_level == "high" and role not in {"ADMIN", "MANAGER"}:
            decision = PermissionDecision(
                decision="ask",
                reason="high_risk_requires_privileged_role",
                source="rbac",
                tool_name=tool.name,
                user_id=user_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            )
            await self._log(decision)
            return decision

        decision = PermissionDecision(
            decision="allow",
            reason="policy_pass",
            source="rbac",
            tool_name=tool.name,
            user_id=user_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )
        await self._log(decision)
        return decision

    async def list_decisions(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        if self.redis is None:
            return []
        key = f"runtime:tool_decisions:{tenant_id}"
        rows = await self.redis.lrange(key, max(offset, 0), max(offset, 0) + max(limit - 1, 0))
        items = []
        for row in rows:
            try:
                items.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        return items

    async def _log(self, decision: PermissionDecision) -> None:
        if self.redis is None:
            return
        key = f"runtime:tool_decisions:{decision.tenant_id}"
        await self.redis.lpush(key, json.dumps(decision.to_dict(), ensure_ascii=False))
        await self.redis.ltrim(key, 0, 499)
        await self.redis.expire(key, 14 * 24 * 3600)
