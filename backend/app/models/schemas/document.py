"""Pydantic schemas for document APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    file_name: str
    file_type: str
    status: str
    task_id: str | None = None
    percentage: int | None = None
    file_size: int | None = None
    department: str | None = None
    access_level: int | None = None
    chunk_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    page: int
    size: int


class UploadSessionRequest(BaseModel):
    file_name: str
    content_type: str
    file_size: int
    total_parts: int
    department: str | None = None
    access_level: int | None = None
