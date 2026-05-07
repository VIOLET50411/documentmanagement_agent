"""Admin sub-router: users, analytics, pipeline (document ingestion management)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.dependencies import get_db, get_minio_client, get_redis
from app.models.db.document import Document
from app.models.db.user import User
from app.models.schemas.user import AdminResetPasswordResponse, AdminUpdateUserRequest, UserResponse

from app.api.v1.admin._helpers import _error_signature

router = APIRouter()


@router.get("/users", response_model=List[UserResponse])
async def list_users(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.auth_service import AuthService

    return await AuthService(db).list_users(tenant_id=current_user.tenant_id)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.auth_service import AuthService

    try:
        return await AuthService(db).admin_update_user(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            user_id=user_id,
            username=payload.username,
            role=payload.role,
            department=payload.department,
            level=payload.level,
            is_active=payload.is_active,
            email_verified=payload.email_verified,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/{user_id}/reset-password", response_model=AdminResetPasswordResponse)
async def reset_user_password(
    user_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.auth_service import AuthService

    try:
        user, temporary_password = await AuthService(db).admin_reset_password(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            user_id=user_id,
        )
        return AdminResetPasswordResponse(
            user_id=user.id,
            username=user.username,
            temporary_password=temporary_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.auth_service import AuthService

    try:
        user = await AuthService(db).admin_delete_user(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            user_id=user_id,
        )
        return {"ok": True, "deleted_user_id": user.id, "deleted_username": user.username}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/analytics/overview")
async def get_analytics_overview(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.analytics_service import AnalyticsService

    return await AnalyticsService(db).get_overview(tenant_id=current_user.tenant_id)


@router.get("/pipeline/status")
async def get_pipeline_status(current_user: User = Depends(require_role("ADMIN"))):
    redis = get_redis()
    if redis is None:
        return {"active": 0, "queued": 0, "failed": 0, "completed": 0}

    active = queued = failed = completed = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match="doc_progress:*", count=200)
        for key in keys or []:
            status = await redis.hget(key, "status")
            if status in ("queued", "parsing", "chunking", "indexing", "retrying"):
                active += 1
                queued += 1 if status == "queued" else 0
            elif status in ("failed", "partial_failed"):
                failed += 1
            elif status == "ready":
                completed += 1
        if cursor == 0:
            break
    return {"active": active, "queued": queued, "failed": failed, "completed": completed}


@router.get("/pipeline/jobs")
async def get_pipeline_jobs(
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    base_query = select(Document).where(Document.tenant_id == current_user.tenant_id)
    if status:
        if status == "failed_family":
            base_query = base_query.where(Document.status.in_(["failed", "partial_failed"]))
        else:
            base_query = base_query.where(Document.status == status)
    total = int((await db.execute(select(func.count()).select_from(base_query.subquery()))).scalar() or 0)
    result = await db.execute(base_query.order_by(Document.updated_at.desc()).offset(max(offset, 0)).limit(max(limit, 1)))
    documents = result.scalars().all()
    redis = get_redis()
    jobs = []
    for document in documents:
        progress = await redis.hgetall(f"doc_progress:{document.id}") if redis is not None else {}
        jobs.append(
            {
                "doc_id": document.id,
                "title": document.title,
                "status": progress.get("status", document.status),
                "percentage": int(progress.get("percentage", 0) or 0),
                "task_id": progress.get("task_id"),
                "attempt": int(progress.get("attempt", 0) or 0),
                "detail": progress.get("detail"),
                "chunk_count": document.chunk_count,
                "file_size": document.file_size,
                "error_message": progress.get("error") or document.error_message,
                "updated_at": progress.get("updated_at") or document.updated_at.isoformat(),
            }
        )
    return {"jobs": jobs, "total": total, "offset": max(offset, 0), "limit": max(limit, 1)}


@router.post("/pipeline/{doc_id}/retry")
async def retry_pipeline_job(
    doc_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_service import DocumentService

    result = await DocumentService(db, get_minio_client()).enqueue_retry(doc_id=doc_id, user=current_user)
    return result


@router.post("/pipeline/retry-failed")
async def retry_failed_pipeline_jobs(
    limit: int = 20,
    include_partial_failed: bool = True,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_service import DocumentService

    statuses = ["failed", "partial_failed"] if include_partial_failed else ["failed"]
    rows = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id, Document.status.in_(statuses))
        .order_by(Document.updated_at.desc())
        .limit(max(limit, 1))
    )
    documents = rows.scalars().all()
    service = DocumentService(db, get_minio_client())
    queued = []
    for item in documents:
        result = await service.enqueue_retry(doc_id=item.id, user=current_user)
        queued.append(result)
    return {"queued_count": len(queued), "queued": queued}


@router.get("/pipeline/failure-summary")
async def get_pipeline_failure_summary(
    limit: int = 20,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id, Document.status.in_(["failed", "partial_failed"]))
        .order_by(Document.updated_at.desc())
        .limit(500)
    )
    documents = rows.scalars().all()
    grouped: dict[str, dict] = {}
    for item in documents:
        signature = _error_signature(item.error_message)
        slot = grouped.setdefault(
            signature,
            {
                "signature": signature,
                "count": 0,
                "latest_at": item.updated_at.isoformat(),
                "example_error": item.error_message or "",
                "status_breakdown": {"failed": 0, "partial_failed": 0},
                "doc_ids": [],
            },
        )
        slot["count"] += 1
        slot["latest_at"] = max(slot["latest_at"], item.updated_at.isoformat())
        slot["example_error"] = slot["example_error"] or (item.error_message or "")
        slot["status_breakdown"][item.status] = slot["status_breakdown"].get(item.status, 0) + 1
        if len(slot["doc_ids"]) < 10:
            slot["doc_ids"].append(item.id)

    items = sorted(grouped.values(), key=lambda x: (x["count"], x["latest_at"]), reverse=True)[: max(limit, 1)]
    return {"items": items, "total": len(grouped), "source_count": len(documents)}


@router.post("/pipeline/retry-by-signature")
async def retry_pipeline_jobs_by_signature(
    signature: str,
    limit: int = 20,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_service import DocumentService

    rows = await db.execute(
        select(Document)
        .where(Document.tenant_id == current_user.tenant_id, Document.status.in_(["failed", "partial_failed"]))
        .order_by(Document.updated_at.desc())
        .limit(500)
    )
    documents = rows.scalars().all()
    matched = [item for item in documents if _error_signature(item.error_message) == signature][: max(limit, 1)]
    service = DocumentService(db, get_minio_client())
    queued = []
    for item in matched:
        queued.append(await service.enqueue_retry(doc_id=item.id, user=current_user))
    return {"signature": signature, "matched_count": len(matched), "queued_count": len(queued), "queued": queued}


@router.post("/reindex")
async def reindex_documents(limit: int | None = None, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.index_sync_service import IndexSyncService

    return await IndexSyncService(db).reindex_tenant(current_user.tenant_id, limit=limit)
