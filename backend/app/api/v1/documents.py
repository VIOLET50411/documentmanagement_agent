"""Documents API - upload, manage, and track processing status."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import get_current_user
from app.api.middleware.rate_limit import rate_limit_check
from app.config import settings
from app.dependencies import get_db, get_minio_client, get_redis
from app.models.db.document import Document
from app.models.db.user import User
from app.models.schemas.document import DocumentListResponse, DocumentResponse, UploadSessionRequest
from app.security.file_scanner import FileScanner
from app.services.document_service import DocumentService
from app.services.security_audit_service import SecurityAuditService

router = APIRouter()
UPLOAD_TMP_ROOT = Path(tempfile.gettempdir()) / "docmind_chunk_uploads"
UPLOAD_COMPLETE_SEMAPHORE = asyncio.Semaphore(2)


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    department: str | None = None,
    access_level: int = 1,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await rate_limit_check(None, f"upload:{current_user.id}", limit=40, window=60)

    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/csv",
        "text/html",
        "image/png",
        "image/jpeg",
    }
    if file.content_type not in allowed_types:
        await SecurityAuditService(get_redis(), db).log_event(
            current_user.tenant_id,
            "upload_rejected",
            "medium",
            "不支持的文件类型",
            user_id=current_user.id,
            target=file.filename,
            result="blocked",
            metadata={"file_name": file.filename, "content_type": file.content_type},
        )
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    size = await _measure_upload_size(file)
    if size > settings.max_upload_size_mb * 1024 * 1024:
        await SecurityAuditService(get_redis(), db).log_event(
            current_user.tenant_id,
            "upload_rejected",
            "medium",
            "文件超过大小限制",
            user_id=current_user.id,
            target=file.filename,
            result="blocked",
            metadata={"file_name": file.filename, "size": size},
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max allowed: {settings.max_upload_size_mb}MB",
        )

    scan_result = await _scan_upload_sample(file, size)
    if not scan_result.get("safe", True):
        await SecurityAuditService(get_redis(), db).log_event(
            current_user.tenant_id,
            "upload_blocked",
            "high",
            "文件安全扫描未通过",
            user_id=current_user.id,
            target=file.filename,
            result="blocked",
            metadata={"file_name": file.filename, "reason": scan_result.get("reason"), "engine": scan_result.get("engine")},
        )
        raise HTTPException(status_code=400, detail=f"文件未通过安全扫描: {scan_result.get('reason')}")

    doc_id = str(uuid.uuid4())
    doc_service = DocumentService(db, get_minio_client())
    return await doc_service.store_and_enqueue(
        doc_id=doc_id,
        file=file,
        uploader_id=current_user.id,
        tenant_id=current_user.tenant_id,
        department=department or current_user.department or "public",
        access_level=access_level or current_user.level,
    )


@router.post("/upload/session")
async def create_upload_session(
    payload: UploadSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await rate_limit_check(None, f"upload:{current_user.id}", limit=40, window=60)
    if int(payload.total_parts or 0) < 1:
        raise HTTPException(status_code=400, detail="分片总数必须大于 0")
    _validate_upload_constraints(
        file_name=payload.file_name,
        content_type=payload.content_type,
        file_size=payload.file_size,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        db=db,
    )

    upload_id = str(uuid.uuid4())
    upload_dir = UPLOAD_TMP_ROOT / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    redis = get_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="上传会话存储不可用")

    response_payload = {
        "upload_id": upload_id,
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "file_size": int(payload.file_size),
        "total_parts": int(payload.total_parts),
        "department": payload.department or current_user.department or "public",
        "access_level": int(payload.access_level or current_user.level),
        "tenant_id": current_user.tenant_id,
        "uploader_id": current_user.id,
        "upload_dir": str(upload_dir),
    }
    await redis.set(f"upload:session:{upload_id}", json.dumps(response_payload, ensure_ascii=False), ex=24 * 3600)
    return response_payload


@router.post("/upload/chunk")
async def upload_document_chunk(
    upload_id: str = Form(...),
    part_number: int = Form(...),
    total_parts: int = Form(...),
    chunk: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    redis = get_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="上传会话存储不可用")
    session = await _get_upload_session(redis, upload_id, current_user.tenant_id)
    if total_parts != int(session["total_parts"]):
        raise HTTPException(status_code=400, detail="分片总数不匹配")
    if part_number < 1 or part_number > total_parts:
        raise HTTPException(status_code=400, detail="分片编号非法")

    upload_dir = Path(session["upload_dir"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"part-{part_number:05d}.bin"
    await _write_chunk_to_disk(chunk, target)
    await chunk.close()

    await redis.sadd(f"upload:parts:{upload_id}", str(part_number))
    await redis.expire(f"upload:parts:{upload_id}", 24 * 3600)
    uploaded_count = await redis.scard(f"upload:parts:{upload_id}")
    percentage = int(uploaded_count * 100 / max(total_parts, 1))
    return {
        "upload_id": upload_id,
        "part_number": part_number,
        "uploaded_parts": int(uploaded_count or 0),
        "total_parts": total_parts,
        "percentage": percentage,
    }


@router.post("/upload/complete", response_model=DocumentResponse, status_code=202)
async def complete_chunk_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = get_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="上传会话存储不可用")
    session = await _get_upload_session(redis, upload_id, current_user.tenant_id)
    total_parts = int(session["total_parts"])
    uploaded_count = await redis.scard(f"upload:parts:{upload_id}")
    if int(uploaded_count or 0) != total_parts:
        raise HTTPException(status_code=400, detail="仍有分片未上传完成")

    upload_dir = Path(session["upload_dir"])
    merged_path = upload_dir / "merged.bin"
    try:
        async with UPLOAD_COMPLETE_SEMAPHORE:
            await asyncio.to_thread(_merge_uploaded_parts, upload_dir, merged_path, total_parts)
            expected_size = int(session.get("file_size") or 0)
            actual_size = merged_path.stat().st_size
            if expected_size > 0 and actual_size != expected_size:
                await SecurityAuditService(get_redis(), db).log_event(
                    current_user.tenant_id,
                    "upload_size_mismatch",
                    "medium",
                    f"分片合并后的文件大小与会话声明不一致: expected={expected_size}, actual={actual_size}",
                    user_id=current_user.id,
                    target=session["file_name"],
                    result="warning",
                    metadata={
                        "file_name": session["file_name"],
                        "expected_size": expected_size,
                        "actual_size": actual_size,
                        "upload_id": upload_id,
                    },
                )
            scan_result = await asyncio.to_thread(_scan_local_file_sample, merged_path)
        if not scan_result.get("safe", True):
            await SecurityAuditService(get_redis(), db).log_event(
                current_user.tenant_id,
                "upload_blocked",
                "high",
                "分片文件安全扫描未通过",
                user_id=current_user.id,
                target=session["file_name"],
                result="blocked",
                metadata={"file_name": session["file_name"], "reason": scan_result.get("reason"), "engine": scan_result.get("engine")},
            )
            raise HTTPException(status_code=400, detail=f"文件未通过安全扫描: {scan_result.get('reason')}")

        doc_id = str(uuid.uuid4())
        doc_service = DocumentService(db, get_minio_client())
        return await doc_service.store_local_file_and_enqueue(
            doc_id=doc_id,
            local_path=str(merged_path),
            file_name=session["file_name"],
            content_type=session["content_type"],
            uploader_id=current_user.id,
            tenant_id=current_user.tenant_id,
            department=session["department"],
            access_level=int(session["access_level"]),
        )
    finally:
        await _cleanup_upload_session(redis, upload_id, upload_dir)


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    department: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService(db, get_minio_client()).list_documents(
        user=current_user,
        page=page,
        size=size,
        department=department,
        status=status,
    )


@router.get("/{doc_id}/status")
async def get_processing_status(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = await db.scalar(select(Document).where(Document.id == doc_id, Document.tenant_id == current_user.tenant_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    redis = get_redis()
    if redis is None:
        return {
            "doc_id": doc_id,
            "status": document.status,
            "percentage": 0,
            "chunk_count": document.chunk_count,
            "error_message": document.error_message,
        }

    progress = await redis.hgetall(f"doc_progress:{doc_id}")
    return {
        "doc_id": doc_id,
        "status": progress.get("status", document.status),
        "percentage": int(progress.get("percentage", 0) or 0),
        "task_id": progress.get("task_id"),
        "attempt": int(progress.get("attempt", 0) or 0),
        "detail": progress.get("detail"),
        "chunk_count": document.chunk_count,
        "error_message": progress.get("error") or document.error_message,
        "updated_at": progress.get("updated_at") or document.updated_at.isoformat(),
    }


@router.get("/{doc_id}/events")
async def get_processing_events(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    document = await db.scalar(select(Document).where(Document.id == doc_id, Document.tenant_id == current_user.tenant_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    redis = get_redis()
    if redis is None:
        return {"doc_id": doc_id, "events": []}
    rows = await redis.lrange(f"doc_progress_events:{doc_id}", 0, 49)
    events = []
    for row in rows:
        try:
            events.append(json.loads(row))
        except json.JSONDecodeError:
            continue
    return {"doc_id": doc_id, "events": events}


@router.get("/{doc_id}/original")
async def get_original_document_access(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = select(Document).where(Document.id == doc_id, Document.tenant_id == current_user.tenant_id)
    if current_user.role != "ADMIN":
        query = query.where(Document.access_level <= current_user.level)
        if current_user.department:
            query = query.where(Document.department.in_([current_user.department, "public"]))

    document = (await db.execute(query)).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        minio_response = await asyncio.to_thread(
            get_minio_client().get_object,
            settings.minio_bucket,
            document.minio_path,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to load original document") from exc

    async def file_iterator():
        try:
            while True:
                chunk = await asyncio.to_thread(minio_response.read, 1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(minio_response.close)
            await asyncio.to_thread(minio_response.release_conn)

    return StreamingResponse(
        file_iterator(),
        media_type=document.file_type or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"inline; filename=document; filename*=UTF-8''{quote(document.file_name)}"
            )
        },
    )


@router.post("/{doc_id}/retry")
async def retry_document(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        result = await DocumentService(db, get_minio_client()).enqueue_retry(doc_id=doc_id, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await DocumentService(db, get_minio_client()).delete_document(doc_id=doc_id, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "doc_id": doc_id}


def _validate_upload_constraints(*, file_name: str, content_type: str, file_size: int, tenant_id: str, user_id: str, db: AsyncSession) -> None:
    allowed_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/csv",
        "text/html",
        "image/png",
        "image/jpeg",
    }
    if content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")
    if file_size > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max allowed: {settings.max_upload_size_mb}MB",
        )


async def _get_upload_session(redis, upload_id: str, tenant_id: str) -> dict:
    raw = await redis.get(f"upload:session:{upload_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="上传会话不存在或已过期")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="上传会话损坏") from exc
    if payload.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="上传会话不存在")
    return payload


async def _cleanup_upload_session(redis, upload_id: str, upload_dir: Path) -> None:
    await redis.delete(f"upload:session:{upload_id}")
    await redis.delete(f"upload:parts:{upload_id}")
    shutil.rmtree(upload_dir, ignore_errors=True)


async def _measure_upload_size(file: UploadFile) -> int:
    file_obj = file.file
    await asyncio.to_thread(file_obj.seek, 0, 2)
    size = await asyncio.to_thread(file_obj.tell)
    await asyncio.to_thread(file_obj.seek, 0)
    return int(size or 0)


async def _scan_upload_sample(file: UploadFile, size: int) -> dict:
    file_obj = file.file
    sample = await asyncio.to_thread(file_obj.read, min(size, 1024 * 1024))
    await asyncio.to_thread(file_obj.seek, 0)
    return await asyncio.to_thread(FileScanner().scan_bytes, sample)


async def _write_chunk_to_disk(chunk: UploadFile, target: Path) -> None:
    with target.open("wb") as file_obj:
        while True:
            data = await chunk.read(1024 * 1024)
            if not data:
                break
            await asyncio.to_thread(file_obj.write, data)


def _merge_uploaded_parts(upload_dir: Path, merged_path: Path, total_parts: int) -> None:
    with merged_path.open("wb") as merged:
        for part_number in range(1, total_parts + 1):
            part_path = upload_dir / f"part-{part_number:05d}.bin"
            if not part_path.exists():
                raise HTTPException(status_code=400, detail=f"缺少分片 {part_number}")
            with part_path.open("rb") as source:
                shutil.copyfileobj(source, merged, length=1024 * 1024)


def _scan_local_file_sample(path: Path) -> dict:
    with path.open("rb") as source:
        sample = source.read(min(1024 * 1024, path.stat().st_size))
    return FileScanner().scan_bytes(sample)
