"""Persistence helpers for runtime graph checkpoints."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.db.runtime_checkpoint import RuntimeCheckpoint


class RuntimeCheckpointStore:
    """Store and retrieve runtime checkpoints from PostgreSQL."""

    def __init__(self, db: AsyncSession | None = None, session_factory: async_sessionmaker[AsyncSession] | None = None):
        self.db = db
        self.session_factory = session_factory

    async def save(self, *, session_id: str, tenant_id: str, trace_id: str, node_name: str, iteration: int, payload: dict[str, Any]) -> RuntimeCheckpoint:
        checkpoint = RuntimeCheckpoint(
            session_id=session_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            node_name=node_name,
            iteration=iteration,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        if self.session_factory is not None:
            async with self.session_factory() as db:
                db.add(checkpoint)
                await db.commit()
                await db.refresh(checkpoint)
                return checkpoint
        if self.db is None:
            raise RuntimeError("RuntimeCheckpointStore requires either db or session_factory.")
        self.db.add(checkpoint)
        await self.db.flush()
        return checkpoint

    async def latest_for_trace(self, trace_id: str) -> RuntimeCheckpoint | None:
        db = self.db
        if self.session_factory is not None:
            async with self.session_factory() as db:
                rows = await db.execute(
                    select(RuntimeCheckpoint)
                    .where(RuntimeCheckpoint.trace_id == trace_id)
                    .order_by(RuntimeCheckpoint.created_at.desc())
                    .limit(1)
                )
                return rows.scalar_one_or_none()
        if db is None:
            return None
        rows = await db.execute(
            select(RuntimeCheckpoint)
            .where(RuntimeCheckpoint.trace_id == trace_id)
            .order_by(RuntimeCheckpoint.created_at.desc())
            .limit(1)
        )
        return rows.scalar_one_or_none()

    async def list_for_session(self, session_id: str, limit: int = 50) -> list[RuntimeCheckpoint]:
        db = self.db
        if self.session_factory is not None:
            async with self.session_factory() as db:
                rows = await db.execute(
                    select(RuntimeCheckpoint)
                    .where(RuntimeCheckpoint.session_id == session_id)
                    .order_by(RuntimeCheckpoint.created_at.desc())
                    .limit(max(limit, 1))
                )
                return list(rows.scalars().all())
        if db is None:
            return []
        rows = await db.execute(
            select(RuntimeCheckpoint)
            .where(RuntimeCheckpoint.session_id == session_id)
            .order_by(RuntimeCheckpoint.created_at.desc())
            .limit(max(limit, 1))
        )
        return list(rows.scalars().all())

    def deserialize_payload(self, checkpoint: RuntimeCheckpoint) -> dict[str, Any]:
        try:
            return json.loads(checkpoint.payload_json or "{}")
        except json.JSONDecodeError:
            return {}
