"""Analytics service."""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_redis
from app.models.db.document import Document
from app.models.db.feedback import Feedback
from app.models.db.security_audit import SecurityAuditEvent
from app.models.db.session import ChatMessage, ChatSession
from app.models.db.user import User


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self, tenant_id: str) -> dict:
        total_queries = await self.db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatMessage.role == "user", ChatSession.tenant_id == tenant_id)
        )
        total_documents = await self.db.scalar(
            select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)
        )
        total_ready_documents = await self.db.scalar(
            select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id, Document.status == "ready")
        )
        total_chunks = await self.db.scalar(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(Document.tenant_id == tenant_id)
        )

        feedback_rows = await self.db.execute(select(Feedback.rating).where(Feedback.tenant_id == tenant_id))
        ratings = [row[0] for row in feedback_rows]
        avg_satisfaction = (sum(ratings) / len(ratings)) if ratings else 0.0

        cache_hits = await self.db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.tenant_id == tenant_id, ChatMessage.role == "assistant", ChatMessage.agent_used == "cache")
        )
        assistant_messages = await self.db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatSession.tenant_id == tenant_id, ChatMessage.role == "assistant")
        )
        cache_hit_rate = (cache_hits or 0) / assistant_messages if assistant_messages else 0.0

        top_queries_rows = await self.db.execute(
            select(ChatMessage.content, func.count(ChatMessage.id).label("count"))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatMessage.role == "user", ChatSession.tenant_id == tenant_id)
            .group_by(ChatMessage.content)
            .order_by(desc("count"))
            .limit(5)
        )

        recent_feedback_rows = await self.db.execute(
            select(Feedback.rating, Feedback.correction, Feedback.created_at)
            .where(Feedback.tenant_id == tenant_id)
            .order_by(Feedback.created_at.desc())
            .limit(5)
        )

        processing_documents = await self.db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.tenant_id == tenant_id, Document.status.in_(["queued", "parsing", "retrying"]))
        )
        failed_documents = await self.db.scalar(
            select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id, Document.status == "failed")
        )

        security_events = await self.db.scalar(
            select(func.count()).select_from(SecurityAuditEvent).where(SecurityAuditEvent.tenant_id == tenant_id)
        )
        if not security_events:
            redis = get_redis()
            if redis is not None:
                security_events = await redis.llen(f"security_audit:{tenant_id}")

        document_status_rows = await self.db.execute(
            select(Document.status, func.count(Document.id))
            .where(Document.tenant_id == tenant_id)
            .group_by(Document.status)
        )
        role_distribution_rows = await self.db.execute(
            select(User.role, func.count(User.id))
            .where(User.tenant_id == tenant_id)
            .group_by(User.role)
        )
        query_trend_rows = await self.db.execute(
            select(func.date(ChatMessage.created_at).label("day"), func.count(ChatMessage.id))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(ChatMessage.role == "user", ChatSession.tenant_id == tenant_id)
            .group_by(func.date(ChatMessage.created_at))
            .order_by(func.date(ChatMessage.created_at).desc())
            .limit(7)
        )
        feedback_distribution_rows = await self.db.execute(
            select(Feedback.rating, func.count(Feedback.id))
            .where(Feedback.tenant_id == tenant_id)
            .group_by(Feedback.rating)
            .order_by(Feedback.rating.desc())
        )

        return {
            "total_queries": int(total_queries or 0),
            "total_documents": int(total_documents or 0),
            "ready_documents": int(total_ready_documents or 0),
            "processing_documents": int(processing_documents or 0),
            "failed_documents": int(failed_documents or 0),
            "total_chunks": int(total_chunks or 0),
            "avg_satisfaction": round(avg_satisfaction, 4),
            "cache_hit_rate": round(cache_hit_rate, 4),
            "security_event_count": int(security_events or 0),
            "top_queries": [{"query": row[0], "count": row[1]} for row in top_queries_rows],
            "recent_feedback": [
                {"rating": row[0], "correction": row[1], "created_at": row[2].isoformat()}
                for row in recent_feedback_rows
            ],
            "document_status_distribution": [
                {"status": row[0] or "unknown", "count": int(row[1] or 0)}
                for row in document_status_rows
            ],
            "role_distribution": [
                {"role": row[0] or "unknown", "count": int(row[1] or 0)}
                for row in role_distribution_rows
            ],
            "query_trend_7d": [
                {"day": str(row[0]), "count": int(row[1] or 0)}
                for row in reversed(query_trend_rows.all())
            ],
            "feedback_distribution": [
                {"rating": int(row[0]), "count": int(row[1] or 0)}
                for row in feedback_distribution_rows
            ],
        }
