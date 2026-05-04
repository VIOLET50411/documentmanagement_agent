"""Feedback service — records user feedback and provides analytics for RLHF."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.feedback import Feedback


class FeedbackService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(self, user_id, tenant_id, message_id, rating, correction=None):
        feedback = Feedback(
            user_id=user_id,
            tenant_id=tenant_id,
            message_id=message_id,
            rating=rating,
            correction=correction,
        )
        self.db.add(feedback)

    async def list_by_tenant(self, tenant_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
        """List feedback entries for a tenant, newest first."""
        rows = await self.db.execute(
            select(Feedback)
            .where(Feedback.tenant_id == tenant_id)
            .order_by(Feedback.created_at.desc())
            .offset(max(offset, 0))
            .limit(max(limit, 1))
        )
        items = rows.scalars().all()
        return [
            {
                "id": item.id,
                "user_id": item.user_id,
                "message_id": item.message_id,
                "rating": item.rating,
                "correction": item.correction,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]

    async def get_stats(self, tenant_id: str) -> dict:
        """Compute feedback statistics: positive/negative/neutral ratio."""
        rows = await self.db.execute(
            select(Feedback.rating, func.count())
            .where(Feedback.tenant_id == tenant_id)
            .group_by(Feedback.rating)
        )
        counts = {str(row[0]): int(row[1]) for row in rows.all()}
        total = sum(counts.values())
        positive = counts.get("1", 0) + counts.get("2", 0)
        negative = counts.get("-1", 0) + counts.get("-2", 0)
        neutral = total - positive - negative
        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "positive_rate": round(positive / max(total, 1), 4),
            "negative_rate": round(negative / max(total, 1), 4),
            "breakdown": counts,
        }

    async def export_for_training(self, tenant_id: str, *, min_rating: int = -2) -> list[dict]:
        """Export negative feedback as DPO/RLHF training candidates."""
        rows = await self.db.execute(
            select(Feedback)
            .where(Feedback.tenant_id == tenant_id, Feedback.rating <= min_rating)
            .order_by(Feedback.created_at.desc())
            .limit(500)
        )
        return [
            {
                "message_id": item.message_id,
                "rating": item.rating,
                "correction": item.correction,
                "user_id": item.user_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in rows.scalars().all()
        ]

    async def flag_low_quality_answers(self, tenant_id: str, *, threshold: int = -1) -> list[dict]:
        """Find message_ids with consistently low feedback for review."""
        rows = await self.db.execute(
            select(Feedback.message_id, func.avg(Feedback.rating).label("avg_rating"), func.count().label("cnt"))
            .where(Feedback.tenant_id == tenant_id)
            .group_by(Feedback.message_id)
            .having(func.avg(Feedback.rating) <= threshold)
            .order_by(func.avg(Feedback.rating).asc())
            .limit(100)
        )
        return [
            {"message_id": row[0], "avg_rating": round(float(row[1]), 2), "feedback_count": int(row[2])}
            for row in rows.all()
        ]
