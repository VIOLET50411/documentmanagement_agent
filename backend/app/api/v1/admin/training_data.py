"""Admin sub-router: training data QA pair review and management."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.dependencies import get_db
from app.models.db.training_qa_pair import TrainingQAPair
from app.models.db.user import User

router = APIRouter()


@router.get("/training-data/qa-pairs")
async def list_qa_pairs(
    status: str | None = None,
    doc_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """List QA pairs with optional status and doc_type filters."""
    query = select(TrainingQAPair).where(TrainingQAPair.tenant_id == current_user.tenant_id)
    count_query = select(func.count()).select_from(TrainingQAPair).where(TrainingQAPair.tenant_id == current_user.tenant_id)
    if status:
        query = query.where(TrainingQAPair.status == status)
        count_query = count_query.where(TrainingQAPair.status == status)
    if doc_type:
        query = query.where(TrainingQAPair.doc_type == doc_type)
        count_query = count_query.where(TrainingQAPair.doc_type == doc_type)

    total = int((await db.execute(count_query)).scalar() or 0)
    rows = await db.execute(
        query.order_by(TrainingQAPair.created_at.desc())
        .offset(max(offset, 0))
        .limit(max(limit, 1))
    )
    items = [
        {
            "id": item.id,
            "doc_id": item.doc_id,
            "chunk_id": item.chunk_id,
            "doc_title": item.doc_title,
            "doc_type": item.doc_type,
            "question": item.question,
            "answer": item.answer,
            "status": item.status,
            "reviewer_id": item.reviewer_id,
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in rows.scalars().all()
    ]
    return {"items": items, "total": total, "offset": max(offset, 0), "limit": max(limit, 1)}


@router.put("/training-data/qa-pairs/{pair_id}/approve")
async def approve_qa_pair(
    pair_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Approve a QA pair for training export."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        update(TrainingQAPair)
        .where(TrainingQAPair.id == pair_id, TrainingQAPair.tenant_id == current_user.tenant_id)
        .values(status="approved", reviewer_id=current_user.id, reviewed_at=now)
    )
    await db.commit()
    return {"ok": result.rowcount > 0, "pair_id": pair_id, "status": "approved"}


@router.put("/training-data/qa-pairs/{pair_id}/reject")
async def reject_qa_pair(
    pair_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Reject a QA pair."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        update(TrainingQAPair)
        .where(TrainingQAPair.id == pair_id, TrainingQAPair.tenant_id == current_user.tenant_id)
        .values(status="rejected", reviewer_id=current_user.id, reviewed_at=now)
    )
    await db.commit()
    return {"ok": result.rowcount > 0, "pair_id": pair_id, "status": "rejected"}


@router.put("/training-data/qa-pairs/{pair_id}/edit")
async def edit_qa_pair(
    pair_id: str,
    question: str | None = None,
    answer: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Edit a QA pair's question or answer."""
    values: dict = {"reviewer_id": current_user.id}
    if question is not None:
        values["question"] = question
    if answer is not None:
        values["answer"] = answer
    result = await db.execute(
        update(TrainingQAPair)
        .where(TrainingQAPair.id == pair_id, TrainingQAPair.tenant_id == current_user.tenant_id)
        .values(**values)
    )
    await db.commit()
    return {"ok": result.rowcount > 0, "pair_id": pair_id}


@router.post("/training-data/export")
async def export_approved_qa_pairs(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Export all approved QA pairs as JSONL-ready SFT training data."""
    rows = await db.execute(
        select(TrainingQAPair)
        .where(TrainingQAPair.tenant_id == current_user.tenant_id, TrainingQAPair.status == "approved")
        .order_by(TrainingQAPair.created_at.asc())
    )
    items = rows.scalars().all()
    export = []
    for item in items:
        export.append({
            "messages": [
                {"role": "system", "content": "你是企业文档问答助手，基于企业内部文档准确回答问题。"},
                {"role": "user", "content": item.question},
                {"role": "assistant", "content": item.answer},
            ],
            "metadata": {
                "doc_id": item.doc_id,
                "doc_type": item.doc_type,
                "doc_title": item.doc_title,
                "pair_id": item.id,
            },
        })
    return {
        "ok": True,
        "count": len(export),
        "data": export,
        "format": "jsonl_messages",
        "tenant_id": current_user.tenant_id,
    }


@router.get("/training-data/stats")
async def get_qa_pair_stats(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Get QA pair statistics by status and doc_type."""
    status_rows = await db.execute(
        select(TrainingQAPair.status, func.count())
        .where(TrainingQAPair.tenant_id == current_user.tenant_id)
        .group_by(TrainingQAPair.status)
    )
    type_rows = await db.execute(
        select(TrainingQAPair.doc_type, func.count())
        .where(TrainingQAPair.tenant_id == current_user.tenant_id)
        .group_by(TrainingQAPair.doc_type)
    )
    return {
        "by_status": {str(row[0]): int(row[1]) for row in status_rows.all()},
        "by_doc_type": {str(row[0]): int(row[1]) for row in type_rows.all()},
        "tenant_id": current_user.tenant_id,
    }
