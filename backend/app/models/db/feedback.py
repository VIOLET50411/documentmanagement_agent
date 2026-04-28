"""
Feedback Model - User feedback for data flywheel.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


class Feedback(Base):
    """User feedback on AI responses (thumbs up/down + corrections)."""

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = thumbs up, -1 = thumbs down
    correction: Mapped[str] = mapped_column(Text, nullable=True)  # User-provided correct answer
    query: Mapped[str] = mapped_column(Text, nullable=True)  # Original query for context
    response: Mapped[str] = mapped_column(Text, nullable=True)  # AI response for context
    sources_json: Mapped[str] = mapped_column(Text, nullable=True)  # Retrieved sources
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
