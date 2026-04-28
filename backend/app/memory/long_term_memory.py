"""Long-term memory management."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class LongTermMemory:
    """Manage persistent user preferences and interests across sessions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_profile(self, user_id: str) -> dict:
        """Load user's long-term memory profile."""
        from app.models.db.user import UserMemory

        result = await self.db.execute(select(UserMemory).where(UserMemory.user_id == user_id))
        memories = result.scalars().all()
        return {
            memory.key: {
                "value": memory.value,
                "type": memory.memory_type,
                "confidence": memory.confidence,
            }
            for memory in memories
        }

    async def update_profile(
        self,
        user_id: str,
        tenant_id: str,
        key: str,
        value: str,
        memory_type: str = "preference",
    ):
        """Update or create a user memory entry."""
        # TODO: [AI_API] Auto-extract preferences from conversation using LLM.
        from app.models.db.user import UserMemory

        existing = await self.db.execute(
            select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.key == key)
        )
        if existing.scalar_one_or_none():
            await self.db.execute(
                update(UserMemory)
                .where(UserMemory.user_id == user_id, UserMemory.key == key)
                .values(value=value, confidence=0.6)
            )
        else:
            memory = UserMemory(
                user_id=user_id,
                tenant_id=tenant_id,
                key=key,
                value=value,
                memory_type=memory_type,
            )
            self.db.add(memory)
