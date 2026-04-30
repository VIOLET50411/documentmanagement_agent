"""Models for LLM training jobs and tenant model registry."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LLMTrainingJob(Base):
    __tablename__ = "llm_training_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    provider: Mapped[str] = mapped_column(String(48), nullable=False, default="mock")
    base_model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    target_model_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    export_dir: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    manifest_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    artifact_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    runtime_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    activated_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    train_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    val_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activate_on_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LLMModelRegistry(Base):
    __tablename__ = "llm_model_registry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    training_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, default="openai-compatible")
    serving_base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    serving_model_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    base_model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    artifact_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_export_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_dataset_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="registered", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)
