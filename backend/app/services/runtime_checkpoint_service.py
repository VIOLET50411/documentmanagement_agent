"""Runtime checkpoint summary and recovery view helpers."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.runtime_checkpoint import RuntimeCheckpoint


class RuntimeCheckpointService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def summarize_sessions(self, tenant_id: str, limit: int = 100) -> list[dict]:
        rows = await self.db.execute(
            select(RuntimeCheckpoint)
            .where(RuntimeCheckpoint.tenant_id == tenant_id)
            .order_by(RuntimeCheckpoint.created_at.desc())
            .limit(max(limit * 10, 100))
        )
        items = rows.scalars().all()

        sessions: dict[str, dict] = {}
        for item in items:
            summary = sessions.setdefault(
                item.session_id,
                {
                    "session_id": item.session_id,
                    "tenant_id": item.tenant_id,
                    "trace_id": item.trace_id,
                    "latest_node_name": item.node_name,
                    "latest_iteration": item.iteration,
                    "latest_at": item.created_at.isoformat(),
                    "checkpoint_count": 0,
                    "resumable": True,
                    "degraded": False,
                    "intent": None,
                    "rewritten_query": None,
                    "answer_preview": "",
                    "warnings": [],
                },
            )
            summary["checkpoint_count"] += 1

            if item.created_at.isoformat() >= summary["latest_at"]:
                payload = self._load_payload(item.payload_json)
                summary.update(
                    {
                        "trace_id": item.trace_id,
                        "latest_node_name": item.node_name,
                        "latest_iteration": item.iteration,
                        "latest_at": item.created_at.isoformat(),
                        "resumable": item.node_name not in {"done", "terminal"},
                        "degraded": bool(payload.get("degraded", False)),
                        "intent": payload.get("intent"),
                        "rewritten_query": payload.get("rewritten_query"),
                        "answer_preview": (payload.get("answer_preview") or payload.get("answer") or "")[:300],
                        "warnings": list(payload.get("warnings") or []),
                    }
                )

        summaries = sorted(sessions.values(), key=lambda row: row["latest_at"], reverse=True)
        return summaries[: max(limit, 1)]

    def _load_payload(self, payload_json: str) -> dict:
        try:
            return json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            return {}
