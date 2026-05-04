"""
Document Model - Document metadata and chunk records.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


class Document(Base):
    """Document metadata record."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    minio_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=True)
    access_level: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # uploaded, queued, parsing, chunking, indexing, retrying, ready, partial_failed, failed
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    uploader_id: Mapped[str] = mapped_column(String(36), nullable=False)
    effective_date: Mapped[str] = mapped_column(String(20), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_doc_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)


class DocumentChunk(Base):
    """Individual chunk of a processed document."""

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    parent_chunk_id: Mapped[str] = mapped_column(String(36), nullable=True)  # Parent-child relationship
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text")  # text, table, image_caption
    section_title: Mapped[str] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSONB-like metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
