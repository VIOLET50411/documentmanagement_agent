"""Celery task definitions for online incremental document processing."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
import redis
from celery.exceptions import Retry
from elasticsearch import ApiError, ConnectionError as ESConnectionError, NotFoundError, TransportError
from minio.error import S3Error

from celery_app import celery
from app.config import settings
from app.ingestion.pipeline import DocumentIngestionPipeline
from app.retrieval.es_client import ESClient
from app.retrieval.milvus_client import MilvusClient
from app.services.push_notification_service import PushNotificationService

try:
    from pymilvus.exceptions import MilvusException
except ImportError:  # pragma: no cover - optional dependency import fallback
    MilvusException = RuntimeError

LARGE_FILE_THRESHOLD_BYTES = 50 * 1024 * 1024
DEFAULT_BATCH_SIZE = 120
LARGE_FILE_BATCH_SIZE = 60
PDF_HEAVY_BATCH_SIZE = 40


@celery.task(bind=True, max_retries=3, acks_late=True)
def process_document(self, doc_id: str, object_path: str, metadata: dict):
    """Main document processing pipeline for uploaded documents."""
    temp_path = None
    attempt = self.request.retries + 1
    task_id = self.request.id or ""
    try:
        _upsert_runtime_task(
            task_id=task_id,
            tenant_id=str(metadata.get("tenant_id") or "default"),
            task_type="ingestion",
            status="running",
            description=f"文档入库任务: {doc_id}",
            stage="queued",
            retries=attempt - 1,
        )
        _set_document_status(doc_id, "queued")
        _update_progress(doc_id, "queued", 0, task_id=task_id, attempt=attempt, detail="任务已入队", tenant_id=str(metadata.get("tenant_id") or "default"))

        _set_document_status(doc_id, "parsing")
        _update_progress(doc_id, "parsing", 8, task_id=task_id, attempt=attempt, detail="开始下载原始文件", tenant_id=str(metadata.get("tenant_id") or "default"))
        temp_path = _download_from_minio(object_path, metadata)

        pipeline = DocumentIngestionPipeline()
        _update_progress(doc_id, "parsing", 20, task_id=task_id, attempt=attempt, detail="开始解析文档", tenant_id=str(metadata.get("tenant_id") or "default"))
        parsed = pipeline.parse_file(temp_path, metadata | {"doc_id": doc_id, "file_name": metadata.get("file_name") or Path(object_path).name})
        elements = parsed["elements"]
        if not elements:
            raise ValueError("文档解析结果为空")

        batches = _split_elements_for_batches(elements, metadata)
        _set_document_status(doc_id, "chunking")
        _update_progress(
            doc_id,
            "chunking",
            35,
            task_id=task_id,
            attempt=attempt,
            detail=f"解析完成，共 {len(elements)} 个元素，拆分为 {len(batches)} 批",
            tenant_id=str(metadata.get("tenant_id") or "default"),
        )

        all_chunks: list[dict] = []
        all_graph_triples: list[dict] = []
        partial_failures = 0
        batch_errors: list[str] = []
        total_parent = 0
        total_child = 0

        for index, batch in enumerate(batches, start=1):
            try:
                batch_result = pipeline.process_elements(
                    batch,
                    metadata
                    | {
                        "doc_id": doc_id,
                        "file_name": metadata.get("file_name") or Path(object_path).name,
                        "batch_index": index,
                        "batch_total": len(batches),
                    },
                )
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                partial_failures += 1
                batch_errors.append(f"第 {index} 批失败: {exc}")
            else:
                all_chunks.extend(batch_result["chunks"])
                all_graph_triples.extend(batch_result["graph_triples"])
                total_parent += batch_result["stats"]["parent_count"]
                total_child += batch_result["stats"]["child_count"]

            percentage = min(80, 35 + int(45 * index / max(len(batches), 1)))
            _update_progress(
                doc_id,
                "chunking",
                percentage,
                task_id=task_id,
                attempt=attempt,
                detail=f"批处理进度 {index}/{len(batches)}",
                tenant_id=str(metadata.get("tenant_id") or "default"),
            )

        if not all_chunks:
            raise ValueError("分块结果为空，无法建立检索索引")

        _persist_chunks(doc_id, all_chunks, all_graph_triples)
        _set_document_status(doc_id, "indexing")
        _update_progress(doc_id, "indexing", 88, task_id=task_id, attempt=attempt, detail="正在同步检索索引", tenant_id=str(metadata.get("tenant_id") or "default"))

        index_result = _sync_external_indices(doc_id, all_chunks)
        degraded_backends = [name for name, item in index_result.items() if not item.get("ok")]

        final_status = "ready"
        detail_segments = [
            f"处理完成，分块 {len(all_chunks)}",
            f"父块 {total_parent}",
            f"子块 {total_child}",
            f"图谱关系 {len(all_graph_triples)}",
        ]
        error_message = None
        if partial_failures > 0 or degraded_backends:
            final_status = "partial_failed"
            detail_segments.append(f"部分失败 {partial_failures} 批")
            if degraded_backends:
                detail_segments.append(f"后端降级: {', '.join(degraded_backends)}")
            error_message = "; ".join(batch_errors + [item["error"] for item in index_result.values() if item.get("error")])[:2000]

        _set_document_status(doc_id, final_status, chunk_count=len(all_chunks), error_message=error_message)
        _update_progress(
            doc_id,
            final_status,
            100,
            task_id=task_id,
            attempt=attempt,
            detail="；".join(detail_segments),
            tenant_id=str(metadata.get("tenant_id") or "default"),
        )
        _upsert_runtime_task(
            task_id=task_id,
            tenant_id=str(metadata.get("tenant_id") or "default"),
            task_type="ingestion",
            status="completed" if final_status == "ready" else "failed",
            description=f"文档入库任务: {doc_id}",
            stage=final_status,
            retries=attempt - 1,
            error=error_message,
            terminal=True,
        )
        _notify_document_status(
            tenant_id=str(metadata.get("tenant_id") or "default"),
            user_id=str(metadata.get("uploader_id") or ""),
            document_id=doc_id,
            title=str(metadata.get("file_name") or doc_id),
            status=final_status,
        )

        return {
            "doc_id": doc_id,
            "chunks": len(all_chunks),
            "graph_triples": len(all_graph_triples),
            "status": final_status,
            "partial_failures": partial_failures,
            "degraded_backends": degraded_backends,
        }
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError, psycopg2.Error, redis.exceptions.RedisError, S3Error, Retry) as exc:
        has_retry = self.request.retries < self.max_retries
        _set_document_status(doc_id, "retrying" if has_retry else "failed", error_message=str(exc))
        _update_progress(
            doc_id,
            "retrying" if has_retry else "failed",
            0,
            error=str(exc),
            task_id=task_id,
            attempt=attempt,
            detail="准备重试" if has_retry else "处理失败",
            tenant_id=str(metadata.get("tenant_id") or "default"),
        )
        _upsert_runtime_task(
            task_id=task_id,
            tenant_id=str(metadata.get("tenant_id") or "default"),
            task_type="ingestion",
            status="running" if has_retry else "failed",
            description=f"文档入库任务: {doc_id}",
            stage="retrying" if has_retry else "failed",
            retries=attempt - 1,
            error=str(exc),
            terminal=not has_retry,
        )
        if not has_retry:
            _notify_document_status(
                tenant_id=str(metadata.get("tenant_id") or "default"),
                user_id=str(metadata.get("uploader_id") or ""),
                document_id=doc_id,
                title=str(metadata.get("file_name") or doc_id),
                status="failed",
            )
        if has_retry:
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        raise
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _split_elements_for_batches(elements: list[dict], metadata: dict) -> list[list[dict]]:
    file_type = str(metadata.get("file_type") or "").lower()
    file_size = int(metadata.get("file_size") or 0)

    batch_size = DEFAULT_BATCH_SIZE
    if file_size > LARGE_FILE_THRESHOLD_BYTES:
        batch_size = LARGE_FILE_BATCH_SIZE
    if "pdf" in file_type and len(elements) > 100:
        batch_size = min(batch_size, PDF_HEAVY_BATCH_SIZE)

    return [elements[i : i + batch_size] for i in range(0, len(elements), batch_size)] or [[]]


def _download_from_minio(object_path: str, metadata: dict) -> str:
    from minio import Minio

    suffix = Path(object_path).suffix or _suffix_from_content_type(metadata.get("file_type", ""))
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.close()

    client = Minio(settings.minio_endpoint, access_key=settings.minio_access_key, secret_key=settings.minio_secret_key, secure=settings.minio_secure)
    client.fget_object(settings.minio_bucket, object_path, temp_file.name)
    return temp_file.name


def _suffix_from_content_type(content_type: str) -> str:
    mapping = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/csv": ".csv",
    }
    return mapping.get(content_type, ".bin")


def _persist_chunks(doc_id: str, chunks: list[dict], graph_triples: list[dict]) -> None:
    conn = psycopg2.connect(settings.postgres_dsn_sync)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,))
            rows = [
                (
                    chunk["id"],
                    doc_id,
                    chunk["tenant_id"],
                    chunk.get("parent_id"),
                    index,
                    chunk["content"],
                    chunk.get("content_type", "text"),
                    chunk.get("section_title"),
                    chunk.get("page_number"),
                    chunk.get("token_count", 0),
                    json.dumps(
                        {
                            "access_level": chunk.get("access_level"),
                            "department": chunk.get("department"),
                            "is_parent": chunk.get("is_parent", False),
                            "effective_date": chunk.get("effective_date"),
                            "doc_type": chunk.get("doc_type"),
                            "sensitivity_level": chunk.get("sensitivity_level"),
                            "keywords": chunk.get("keywords", []),
                            "dense_vector": chunk.get("dense_vector"),
                            "sparse_vector": chunk.get("sparse_vector"),
                            "graph_triples": graph_triples[:10],
                        },
                        ensure_ascii=False,
                    ),
                )
                for index, chunk in enumerate(chunks)
            ]
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO document_chunks (
                    id, doc_id, tenant_id, parent_chunk_id, chunk_index, content,
                    content_type, section_title, page_number, token_count, metadata_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                rows,
                page_size=100,
            )
        conn.commit()
    finally:
        conn.close()


def _sync_external_indices(doc_id: str, chunks: list[dict]) -> dict:
    result = {
        "elasticsearch": {"ok": True, "error": None},
        "milvus": {"ok": True, "error": None},
    }
    try:
        ESClient().bulk_index(chunks)
    except (ApiError, TransportError, ESConnectionError, NotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        result["elasticsearch"] = {"ok": False, "error": f"elasticsearch: {exc}"}
    try:
        MilvusClient(dim=len(chunks[0].get("dense_vector", [])) if chunks else 64).upsert_chunks(chunks)
    except (MilvusException, OSError, RuntimeError, TypeError, ValueError) as exc:
        result["milvus"] = {"ok": False, "error": f"milvus: {exc}"}
    return result


def _set_document_status(doc_id: str, status: str, chunk_count: int | None = None, error_message: str | None = None):
    conn = psycopg2.connect(settings.postgres_dsn_sync)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET status = %s,
                    chunk_count = COALESCE(%s, chunk_count),
                    error_message = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    status,
                    chunk_count,
                    error_message[:2000] if error_message else None,
                    doc_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _update_progress(
    doc_id: str,
    status: str,
    percentage: int,
    error: str | None = None,
    task_id: str | None = None,
    attempt: int | None = None,
    detail: str | None = None,
    tenant_id: str | None = None,
):
    client = redis.from_url(settings.redis_url)
    now = datetime.now(timezone.utc).isoformat()
    mapping = {"status": status, "percentage": str(percentage), "updated_at": now}
    if task_id:
        mapping["task_id"] = task_id
    if attempt is not None:
        mapping["attempt"] = str(attempt)
    if detail:
        mapping["detail"] = detail[:200]
    if error:
        mapping["error"] = error[:500]
    client.hset(f"doc_progress:{doc_id}", mapping=mapping)
    client.expire(f"doc_progress:{doc_id}", 7 * 24 * 3600)
    _append_pipeline_event(client, doc_id, mapping)
    if task_id and tenant_id:
        _upsert_runtime_task(
            task_id=task_id,
            tenant_id=tenant_id,
            task_type="ingestion",
            status=_map_stage_to_status(status),
            description=f"文档入库任务: {doc_id}",
            stage=status,
            retries=max((attempt or 1) - 1, 0),
            error=error,
            terminal=status in {"ready", "failed", "partial_failed"},
        )


def _append_pipeline_event(client, doc_id: str, mapping: dict):
    payload = {"doc_id": doc_id, **mapping}
    client.lpush(f"doc_progress_events:{doc_id}", json.dumps(payload, ensure_ascii=False))
    client.ltrim(f"doc_progress_events:{doc_id}", 0, 49)
    client.expire(f"doc_progress_events:{doc_id}", 7 * 24 * 3600)


def _map_stage_to_status(stage: str) -> str:
    stage = (stage or "").lower()
    if stage in {"queued"}:
        return "pending"
    if stage in {"ready"}:
        return "completed"
    if stage in {"failed", "partial_failed"}:
        return "failed"
    return "running"


def _upsert_runtime_task(
    *,
    task_id: str,
    tenant_id: str,
    task_type: str,
    status: str,
    description: str,
    stage: str | None = None,
    retries: int = 0,
    error: str | None = None,
    terminal: bool = False,
) -> None:
    if not task_id:
        return
    client = redis.from_url(settings.redis_url)
    key = f"runtime:task:{task_id}"
    now = datetime.now(timezone.utc).isoformat()
    raw = client.get(key)
    payload = {}
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    if not payload:
        payload = {
            "task_id": task_id,
            "type": task_type,
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
    payload["status"] = status
    payload["description"] = description
    payload["stage"] = stage
    payload["retries"] = retries
    payload["updated_at"] = now
    if error:
        payload["error"] = error[:2000]
    if terminal:
        payload["end_time"] = now

    client.set(key, json.dumps(payload, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
    index_key = f"runtime:tasks:{tenant_id}"
    client.zadd(index_key, {task_id: datetime.now(timezone.utc).timestamp()})
    client.expire(index_key, settings.runtime_task_retention_seconds)


def _notify_document_status(*, tenant_id: str, user_id: str, document_id: str, title: str, status: str) -> None:
    if not user_id:
        return
    PushNotificationService(redis_client=redis.from_url(settings.redis_url)).send_document_status_sync(
        tenant_id=tenant_id,
        user_id=user_id,
        document_id=document_id,
        title=title,
        status=status,
    )

