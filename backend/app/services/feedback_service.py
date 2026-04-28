"""Feedback service."""

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
