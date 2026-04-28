"""Document service: upload, list, status, retry, and delete document records."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from minio.error import S3Error
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_redis
from app.models.db.document import Document, DocumentChunk


class DocumentService:
    def __init__(self, db: AsyncSession, minio_client):
        self.db = db
        self.minio = minio_client

    async def store_and_enqueue(self, doc_id, file, uploader_id, tenant_id, department, access_level):
        file_obj = file.file
        await asyncio.to_thread(file_obj.seek, 0, 2)
        size = await asyncio.to_thread(file_obj.tell)
        await asyncio.to_thread(file_obj.seek, 0)

        object_path = f"{tenant_id}/{doc_id}/{file.filename}"
        part_size = 10 * 1024 * 1024 if size > 20 * 1024 * 1024 else 0
        await asyncio.to_thread(
            self.minio.put_object,
            settings.minio_bucket,
            object_path,
            file_obj,
            size,
            part_size=part_size,
            content_type=file.content_type or "application/octet-stream",
        )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        resolved_department = department or "public"
        resolved_access_level = int(access_level or 1)
        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            title=file.filename,
            file_name=file.filename,
            file_type=file.content_type or "application/octet-stream",
            file_size=size,
            minio_path=object_path,
            department=resolved_department,
            access_level=resolved_access_level,
            uploader_id=uploader_id,
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
        self.db.add(doc)
        await self.db.flush()

        return await self._enqueue_document_processing(
            doc_id=doc_id,
            minio_path=doc.minio_path,
            tenant_id=tenant_id,
            uploader_id=uploader_id,
            department=resolved_department,
            access_level=resolved_access_level,
            file_type=file.content_type,
            file_name=file.filename,
            file_size=size,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )

    async def store_local_file_and_enqueue(
        self,
        *,
        doc_id: str,
        local_path: str,
        file_name: str,
        content_type: str,
        uploader_id: str,
        tenant_id: str,
        department: str,
        access_level: int,
    ):
        path = Path(local_path)
        size = path.stat().st_size
        object_path = f"{tenant_id}/{doc_id}/{file_name}"

        await asyncio.to_thread(
            self.minio.fput_object,
            settings.minio_bucket,
            object_path,
            str(path),
            content_type=content_type or "application/octet-stream",
        )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        resolved_department = department or "public"
        resolved_access_level = int(access_level or 1)
        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            title=file_name,
            file_name=file_name,
            file_type=content_type or "application/octet-stream",
            file_size=size,
            minio_path=object_path,
            department=resolved_department,
            access_level=resolved_access_level,
            uploader_id=uploader_id,
            status="uploaded",
            created_at=now,
            updated_at=now,
        )
        self.db.add(doc)
        await self.db.flush()

        return await self._enqueue_document_processing(
            doc_id=doc_id,
            minio_path=doc.minio_path,
            tenant_id=tenant_id,
            uploader_id=uploader_id,
            department=resolved_department,
            access_level=resolved_access_level,
            file_type=content_type,
            file_name=file_name,
            file_size=size,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )

    async def list_documents(self, *, user, page: int, size: int, department: str | None = None, status: str | None = None):
        query = select(Document).where(Document.tenant_id == user.tenant_id)
        count_query = select(func.count()).select_from(Document).where(Document.tenant_id == user.tenant_id)

        if user.role != "ADMIN":
            query = query.where(Document.access_level <= user.level)
            count_query = count_query.where(Document.access_level <= user.level)
            if user.department:
                query = query.where(Document.department.in_([user.department, "public"]))
                count_query = count_query.where(Document.department.in_([user.department, "public"]))

        if department:
            query = query.where(Document.department == department)
            count_query = count_query.where(Document.department == department)
        if status:
            query = query.where(Document.status == status)
            count_query = count_query.where(Document.status == status)

        total = int((await self.db.execute(count_query)).scalar() or 0)
        rows = await self.db.execute(query.order_by(Document.updated_at.desc()).offset((page - 1) * size).limit(size))
        redis = get_redis()
        documents = []
        for item in rows.scalars().all():
            progress = await redis.hgetall(f"doc_progress:{item.id}") if redis is not None else {}
            documents.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "file_name": item.file_name,
                    "file_type": item.file_type,
                    "status": progress.get("status", item.status),
                    "task_id": progress.get("task_id"),
                    "percentage": int(progress.get("percentage", 0) or 0),
                    "file_size": item.file_size,
                    "department": item.department,
                    "access_level": item.access_level,
                    "chunk_count": item.chunk_count,
                    "error_message": progress.get("error") or item.error_message,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
            )
        return {"documents": documents, "total": total, "page": page, "size": size}

    async def delete_document(self, *, doc_id: str, user) -> None:
        query = select(Document).where(Document.id == doc_id, Document.tenant_id == user.tenant_id)
        if user.role != "ADMIN":
            query = query.where(Document.uploader_id == user.id)
        document = (await self.db.execute(query)).scalar_one_or_none()
        if document is None:
            raise ValueError("Document not found")

        await self.db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
        await self.db.execute(delete(Document).where(Document.id == doc_id))

        try:
            self.minio.remove_object(settings.minio_bucket, document.minio_path)
        except S3Error:
            pass

        redis = get_redis()
        if redis is not None:
            await redis.delete(f"doc_progress:{doc_id}")
            await redis.delete(f"doc_progress_events:{doc_id}")

    async def enqueue_retry(self, *, doc_id: str, user) -> dict:
        document = (
            await self.db.execute(select(Document).where(Document.id == doc_id, Document.tenant_id == user.tenant_id))
        ).scalar_one_or_none()
        if document is None:
            raise ValueError("Document not found")

        task = await self._dispatch_processing_task(
            doc_id=document.id,
            minio_path=document.minio_path,
            tenant_id=document.tenant_id,
            uploader_id=document.uploader_id,
            department=document.department,
            access_level=document.access_level,
            file_type=document.file_type,
            file_name=document.file_name,
            file_size=document.file_size,
        )
        document.status = "queued"
        redis = get_redis()
        if redis is not None:
            await self._upsert_runtime_task(
                task_id=task.id,
                tenant_id=document.tenant_id,
                status="pending",
                description=f"文档重试任务: {document.id}",
                stage="queued",
                retries=0,
            )
        return {"doc_id": document.id, "task_id": task.id, "status": document.status}

    async def _enqueue_document_processing(
        self,
        *,
        doc_id: str,
        minio_path: str,
        tenant_id: str,
        uploader_id: str,
        department: str,
        access_level: int,
        file_type: str,
        file_name: str,
        file_size: int,
        created_at,
        updated_at,
    ) -> dict:
        task = await self._dispatch_processing_task(
            doc_id=doc_id,
            minio_path=minio_path,
            tenant_id=tenant_id,
            uploader_id=uploader_id,
            department=department,
            access_level=access_level,
            file_type=file_type,
            file_name=file_name,
            file_size=file_size,
        )

        redis = get_redis()
        if redis is not None:
            await redis.hset(
                f"doc_progress:{doc_id}",
                mapping={
                    "status": "queued",
                    "percentage": "0",
                    "task_id": task.id,
                    "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    "detail": "任务已入队",
                },
            )
            await redis.expire(f"doc_progress:{doc_id}", 7 * 24 * 3600)
            await self._upsert_runtime_task(
                task_id=task.id,
                tenant_id=tenant_id,
                status="pending",
                description=f"文档入库任务: {doc_id}",
                stage="queued",
                retries=0,
            )

        return {
            "id": doc_id,
            "title": file_name,
            "file_name": file_name,
            "file_type": file_type or "application/octet-stream",
            "status": "queued",
            "task_id": task.id,
            "percentage": 0,
            "file_size": file_size,
            "department": department,
            "access_level": access_level,
            "chunk_count": 0,
            "error_message": None,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    async def _dispatch_processing_task(
        self,
        *,
        doc_id: str,
        minio_path: str,
        tenant_id: str,
        uploader_id: str,
        department: str,
        access_level: int,
        file_type: str,
        file_name: str,
        file_size: int,
    ):
        from app.ingestion.tasks import process_document

        return process_document.apply_async(
            args=(
                doc_id,
                minio_path,
                {
                    "tenant_id": tenant_id,
                    "uploader_id": uploader_id,
                    "department": department,
                    "access_level": access_level,
                    "file_type": file_type,
                    "file_name": file_name,
                    "file_size": file_size,
                    "doc_id": doc_id,
                },
            ),
            queue=settings.celery_ingestion_queue,
        )

    async def _upsert_runtime_task(
        self,
        *,
        task_id: str,
        tenant_id: str,
        status: str,
        description: str,
        stage: str | None,
        retries: int,
    ) -> None:
        redis = get_redis()
        if redis is None:
            return
        key = f"runtime:task:{task_id}"
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        payload = {
            "task_id": task_id,
            "type": "ingestion",
            "status": status,
            "description": description,
            "tool_use_id": None,
            "start_time": now,
            "end_time": None,
            "output_offset": 0,
            "retries": retries,
            "notified": False,
            "trace_id": task_id,
            "tenant_id": tenant_id,
            "session_id": None,
            "stage": stage,
            "error": None,
            "updated_at": now,
        }
        await redis.set(key, json.dumps(payload, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
        index_key = f"runtime:tasks:{tenant_id}"
        await redis.zadd(index_key, {task_id: datetime.now(timezone.utc).timestamp()})
        await redis.expire(index_key, settings.runtime_task_retention_seconds)
