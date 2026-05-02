"""Admin API - user management, analytics, pipeline, security, and evaluation."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.config import settings
from app.dependencies import get_db, get_minio_client, get_redis
from app.models.db.document import Document, DocumentChunk
from app.models.db.user import User
from app.models.schemas.user import UserResponse

router = APIRouter()
REPORTS_DIR = Path(os.getenv("DOCMIND_REPORTS_DIR") or (Path(__file__).resolve().parents[3] / "reports"))
PUBLIC_DATASETS_DIR = Path(os.getenv("DOCMIND_SHARED_DATASETS_DIR") or (Path(__file__).resolve().parents[4] / "datasets"))


def _error_signature(error_message: str | None) -> str:
    if not error_message:
        return "unknown"
    text = error_message.strip().lower()
    text = re.sub(r"[0-9a-f]{8,}", "<hex>", text)
    text = re.sub(r"\d{2,}", "<num>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120]


def _serialize_training_job(item) -> dict:
    payload = {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "source_tenant_id": item.source_tenant_id,
        "dataset_name": item.dataset_name,
        "status": item.status,
        "stage": item.stage,
        "provider": item.provider,
        "base_model": item.base_model,
        "target_model_name": item.target_model_name,
        "export_dir": item.export_dir,
        "manifest_path": item.manifest_path,
        "artifact_dir": item.artifact_dir,
        "runtime_task_id": item.runtime_task_id,
        "activated_model_id": item.activated_model_id,
        "train_records": item.train_records,
        "val_records": item.val_records,
        "activate_on_success": item.activate_on_success,
        "error_message": item.error_message,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
    if item.result_json:
        try:
            payload["result"] = json.loads(item.result_json)
        except json.JSONDecodeError:
            payload["result_raw"] = item.result_json
    return payload


def _serialize_registry_model(item) -> dict:
    metrics = None
    if item.metrics_json:
        try:
            metrics = json.loads(item.metrics_json)
        except json.JSONDecodeError:
            metrics = {"raw": item.metrics_json}
    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "training_job_id": item.training_job_id,
        "model_name": item.model_name,
        "provider": item.provider,
        "serving_base_url": item.serving_base_url,
        "serving_model_name": item.serving_model_name,
        "base_model": item.base_model,
        "artifact_dir": item.artifact_dir,
        "source_export_dir": item.source_export_dir,
        "source_dataset_name": item.source_dataset_name,
        "status": item.status,
        "is_active": item.is_active,
        "canary_percent": item.canary_percent,
        "metrics": metrics,
        "notes": item.notes,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "activated_at": item.activated_at.isoformat() if item.activated_at else None,
    }


async def _seed_runtime_task(task_id: str, *, tenant_id: str, task_type: str, description: str, stage: str = "queued") -> None:
    redis_client = get_redis()
    if redis_client is None:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    payload = {
        "task_id": task_id,
        "type": task_type,
        "status": "pending",
        "description": description,
        "tool_use_id": None,
        "start_time": now,
        "end_time": None,
        "output_offset": 0,
        "retries": 0,
        "notified": False,
        "trace_id": task_id,
        "tenant_id": tenant_id,
        "session_id": None,
        "stage": stage,
        "error": None,
        "updated_at": now,
    }
    await redis_client.set(f"runtime:task:{task_id}", json.dumps(payload, ensure_ascii=False), ex=settings.runtime_task_retention_seconds)
    await redis_client.zadd(f"runtime:tasks:{tenant_id}", {task_id: datetime.now(timezone.utc).timestamp()})
    await redis_client.expire(f"runtime:tasks:{tenant_id}", settings.runtime_task_retention_seconds)


async def _get_runtime_task_payload(task_id: str, *, tenant_id: str, expected_type: str) -> dict:
    from app.agent.runtime.task_store import TERMINAL_STATUSES
    from app.agent.runtime.task_store import TaskStore
    from celery.result import AsyncResult

    from celery_app import celery

    store = TaskStore(get_redis(), retention_seconds=settings.runtime_task_retention_seconds)
    record = await store.get(task_id)
    if record is None or record.tenant_id != tenant_id or record.type != expected_type:
        return {"exists": False, "task_id": task_id}

    result = AsyncResult(task_id, app=celery)
    raw = result.result if result.ready() else None
    if result.ready() and record.status not in TERMINAL_STATUSES:
        if isinstance(raw, dict) and raw.get("ok", True):
            await store.complete(task_id)
        elif isinstance(raw, dict):
            await store.fail(task_id, str(raw.get("error") or f"{expected_type}_failed"))
        else:
            await store.fail(task_id, str(raw))
        record = await store.get(task_id) or record

    payload = {"exists": True, "item": asdict(record), "celery_state": result.state}
    if result.ready():
        payload["result"] = raw if isinstance(raw, dict) else {"value": str(raw)}
    return payload


@router.get("/users", response_model=List[UserResponse])
async def list_users(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.auth_service import AuthService

    return await AuthService(db).list_users(tenant_id=current_user.tenant_id)


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


@router.get("/security/events")
async def get_security_events(
    limit: int = 50,
    offset: int = 0,
    severity: str | None = None,
    action: str | None = None,
    result: str | None = None,
    from_time: str | None = Query(default=None, alias="from"),
    to_time: str | None = Query(default=None, alias="to"),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService

    def parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except ValueError:
            return None

    data = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=limit,
        offset=offset,
        severity=severity,
        action=action,
        result=result,
        from_time=parse_iso(from_time),
        to_time=parse_iso(to_time),
    )
    return data


@router.get("/security/alerts")
async def get_security_alerts(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService

    return await SecurityAuditService(get_redis(), db).list_alerts(current_user.tenant_id, limit=limit, offset=offset)


@router.get("/security/summary")
async def get_security_summary(
    limit: int = 1000,
    severity: str | None = None,
    action: str | None = None,
    result: str | None = None,
    since_hours: int = 24,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from_time = now - timedelta(hours=since_hours) if since_hours > 0 else None
    return await SecurityAuditService(get_redis(), db).summarize_events(
        current_user.tenant_id,
        limit=max(limit, 1),
        severity=severity,
        action=action,
        result=result,
        from_time=from_time,
        to_time=now,
    )


@router.post("/security/watermark/trace")
async def trace_watermark(
    text: str | None = None,
    fingerprint: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.dlp_forensics_service import DLPForensicsService

    service = DLPForensicsService(get_redis(), db)
    if fingerprint:
        result = await service.trace_by_fingerprint(tenant_id=current_user.tenant_id, fingerprint=fingerprint)
        return {"result": result, "found": bool(result), "mode": "fingerprint"}
    if text:
        result = await service.trace_from_text(tenant_id=current_user.tenant_id, text=text)
        return {"result": result, "found": bool(result and result.get("found", True)), "mode": "text"}
    return {"result": None, "found": False, "mode": "none", "message": "请提供 text 或 fingerprint"}


@router.get("/system/backends")
async def get_backend_status(current_user: User = Depends(require_role("ADMIN"))):
    from app.retrieval.es_client import ESClient
    from app.retrieval.milvus_client import MilvusClient
    from app.retrieval.neo4j_client import Neo4jClient
    from app.security.pii_masker import PIIMasker
    from app.services.llm_service import LLMService
    from app.security.file_scanner import FileScanner
    from app.services.guardrails_service import GuardrailsService
    from app.config import settings

    async def run_sync_health(name: str, fn, timeout: float = 2.5):
        try:
            result = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
            if isinstance(result, dict):
                result.setdefault("available", True)
            return name, result
        except Exception as exc:  # noqa: BLE001
            return name, {"available": False, "status": "degraded", "error": str(exc)}

    async def run_async_health(name: str, coro, timeout: float = 2.5):
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            if isinstance(result, dict):
                result.setdefault("available", True)
            return name, result
        except Exception as exc:  # noqa: BLE001
            return name, {"available": False, "status": "degraded", "error": str(exc)}

    def neo4j_health():
        client = Neo4jClient()
        try:
            return client.health()
        finally:
            client.close()

    checks = await asyncio.gather(
        run_sync_health("elasticsearch", lambda: ESClient().health()),
        run_sync_health("milvus", lambda: MilvusClient().health()),
        run_sync_health("neo4j", neo4j_health),
        run_sync_health("clamav", lambda: FileScanner().health()),
        run_async_health("llm", LLMService().health()),
        run_async_health("guardrails", GuardrailsService().health()),
    )
    payload = {name: result for name, result in checks}
    payload["redis"] = {"available": get_redis() is not None}
    payload["pii"] = {
        "available": bool(settings.pii_masking_enabled),
        "presidio_enabled": bool(settings.pii_presidio_enabled),
        "mode": "presidio_patterns" if PIIMasker()._recognizers else "local_regex",
    }
    payload["runtime"] = {"mode": "v2_only"}
    return payload


@router.get("/llm/domain-config")
async def get_llm_domain_config(current_user: User = Depends(require_role("ADMIN"))):
    return {
        "enterprise_enabled": settings.llm_enterprise_enabled,
        "enterprise_model_name": settings.llm_enterprise_model_name,
        "enterprise_api_base_url": settings.llm_enterprise_api_base_url or settings.llm_api_base_url,
        "enterprise_keywords": settings.llm_enterprise_keyword_list,
        "enterprise_force_tenants": settings.llm_enterprise_force_tenant_list,
        "enterprise_canary_percent": settings.llm_enterprise_canary_percent,
        "enterprise_corpus_min_chars": settings.llm_enterprise_corpus_min_chars,
        "tenant_id": current_user.tenant_id,
        "notes": [
            "建议将企业制度、审批、合规、采购、预算等高价值文档导出为领域语料后再做 LoRA/SFT。",
            "若只想先试运行，可先启用 enterprise model 路由，不强制做全量微调。",
        ],
    }


@router.post("/llm/domain-corpus/export")
async def export_llm_domain_corpus(
    doc_limit: int = 200,
    chunk_limit: int = 4000,
    keywords: str | None = None,
    max_access_level: int = 3,
    deduplicate: bool = True,
    train_ratio: float = 0.9,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.enterprise_tuning_service import EnterpriseTuningService

    keyword_list = [item.strip() for item in (keywords or "").split(",") if item.strip()]
    return await EnterpriseTuningService(db, REPORTS_DIR).export_domain_corpus(
        current_user.tenant_id,
        doc_limit=max(doc_limit, 1),
        chunk_limit=max(chunk_limit, 1),
        keywords=keyword_list or None,
        max_access_level=max(max_access_level, 1),
        deduplicate=bool(deduplicate),
        train_ratio=float(train_ratio),
    )


@router.post("/llm/public-corpus/export")
async def export_public_corpus(
    dataset_name: str = "swu_public_docs",
    tenant_id: str = "public_cold_start",
    train_ratio: float = 0.9,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.services.enterprise_tuning_service import EnterpriseTuningService
    from app.services.public_corpus_service import PublicCorpusService

    dataset_root = PUBLIC_DATASETS_DIR / dataset_name
    if not dataset_root.exists():
        return {
            "ok": False,
            "message": f"公开语料目录不存在: {dataset_name}",
            "requested_by": current_user.id,
            "dataset_name": dataset_name,
        }

    records = PublicCorpusService(dataset_root).build_records()
    result = EnterpriseTuningService(db=None, reports_dir=REPORTS_DIR).export_records_bundle(
        tenant_id=tenant_id,
        source_label=dataset_name,
        records=records,
        train_ratio=float(train_ratio),
    )
    result["dataset_name"] = dataset_name
    result["record_count"] = len(records)
    result["requested_by"] = current_user.id
    return result


@router.post("/llm/public-corpus/export-async")
async def export_public_corpus_async(
    dataset_name: str = "swu_public_docs",
    tenant_id: str = "public_cold_start",
    train_ratio: float = 0.9,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.maintenance.tasks import export_public_corpus_job

    dataset_root = PUBLIC_DATASETS_DIR / dataset_name
    if not dataset_root.exists():
        return {
            "ok": False,
            "message": f"公开语料目录不存在: {dataset_name}",
            "requested_by": current_user.id,
            "dataset_name": dataset_name,
        }

    task = export_public_corpus_job.apply_async(
        args=(dataset_name, tenant_id, float(train_ratio), current_user.id),
        queue=settings.celery_maintenance_queue,
    )
    await _seed_runtime_task(
        task.id,
        tenant_id=tenant_id,
        task_type="public_corpus_export",
        description=f"公开语料导出任务: dataset={dataset_name}, tenant={tenant_id}",
    )
    return {
        "task_id": task.id,
        "status": "pending",
        "tenant_id": tenant_id,
        "dataset_name": dataset_name,
        "train_ratio": float(train_ratio),
    }


@router.get("/llm/public-corpus/tasks/{task_id}")
async def get_public_corpus_export_task(
    task_id: str,
    tenant_id: str = "public_cold_start",
    current_user: User = Depends(require_role("ADMIN")),
):
    payload = await _get_runtime_task_payload(task_id, tenant_id=tenant_id, expected_type="public_corpus_export")
    if payload.get("exists"):
        payload["requested_by"] = current_user.id
    return payload


@router.get("/llm/public-corpus/latest")
async def get_latest_public_corpus_export(
    dataset_name: str = "swu_public_docs",
    tenant_id: str = "public_cold_start",
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.services.public_corpus_service import PublicCorpusService

    dataset_root = PUBLIC_DATASETS_DIR / dataset_name
    service = PublicCorpusService(dataset_root if dataset_root.exists() else PUBLIC_DATASETS_DIR)
    summary = service.latest_export_summary(REPORTS_DIR, tenant_id=tenant_id)
    summary["dataset_name"] = dataset_name
    summary["requested_by"] = current_user.id
    return summary


@router.get("/public-corpus/latest")
async def get_latest_public_corpus_export_compat(
    dataset_name: str = "swu_public_docs",
    tenant_id: str = "public_cold_start",
    current_user: User = Depends(require_role("ADMIN")),
):
    return await get_latest_public_corpus_export(
        dataset_name=dataset_name,
        tenant_id=tenant_id,
        current_user=current_user,
    )


@router.post("/llm/training/run-async")
async def run_llm_training_async(
    dataset_name: str = "swu_public_docs",
    source_tenant_id: str = "public_cold_start",
    target_tenant_id: str | None = None,
    export_dir: str | None = None,
    base_model: str | None = None,
    provider: str | None = None,
    activate_on_success: bool = True,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.training.tasks import run_training_job

    effective_target_tenant = target_tenant_id or current_user.tenant_id
    service = LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR)
    job, summary = await service.create_job(
        tenant_id=effective_target_tenant,
        source_tenant_id=source_tenant_id,
        dataset_name=dataset_name,
        export_dir=export_dir,
        base_model=base_model,
        provider=provider,
        activate_on_success=bool(activate_on_success),
        actor_id=current_user.id,
    )
    task = run_training_job.apply_async(args=(job.id,), queue=settings.celery_maintenance_queue)
    await service.attach_runtime_task(job.id, task.id)
    await _seed_runtime_task(
        task.id,
        tenant_id=effective_target_tenant,
        task_type="llm_training",
        description=f"模型训练任务: dataset={dataset_name}, target_tenant={effective_target_tenant}",
    )
    return {
        "ok": True,
        "job": _serialize_training_job(job),
        "task_id": task.id,
        "summary": {
            "export_dir": summary.get("export_dir"),
            "manifest_path": summary.get("manifest_path"),
            "training_readiness": summary.get("training_readiness"),
        },
    }


@router.get("/llm/training/jobs")
async def list_llm_training_jobs(
    tenant_id: str | None = None,
    limit: int = 50,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService

    effective_tenant = tenant_id or current_user.tenant_id
    service = LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR)
    items = await service.list_jobs(effective_tenant, limit=max(limit, 1))
    changed = False
    for item in items:
        if not item.runtime_task_id:
            continue
        runtime_payload = await _get_runtime_task_payload(item.runtime_task_id, tenant_id=effective_tenant, expected_type="llm_training")
        changed = await service.reconcile_job_runtime_state(item, runtime_payload) or changed
    if changed:
        await db.commit()
    return {"items": [_serialize_training_job(item) for item in items], "count": len(items), "tenant_id": effective_tenant}


@router.get("/llm/training/summary")
async def get_llm_training_summary(
    tenant_id: str | None = None,
    limit: int = 100,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService

    effective_tenant = tenant_id or current_user.tenant_id
    service = LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR)
    models = await service.list_models(effective_tenant, limit=max(limit, 1))
    if await service.reconcile_model_registry_states(effective_tenant, models):
        await db.commit()
    summary = await service.summarize_rollout(effective_tenant, limit=max(limit, 1))
    return summary


@router.get("/llm/deployment/summary")
async def get_llm_deployment_summary(
    tenant_id: str | None = None,
    limit: int = 20,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService

    effective_tenant = tenant_id or current_user.tenant_id
    service = LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR)
    models = await service.list_models(effective_tenant, limit=max(limit, 1))
    if await service.reconcile_model_registry_states(effective_tenant, models):
        await db.commit()
    return await service.summarize_deployment(effective_tenant, limit=max(limit, 1))


@router.get("/llm/training/deployment")
async def get_llm_training_deployment_alias(
    tenant_id: str | None = None,
    limit: int = 20,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    return await get_llm_deployment_summary(
        tenant_id=tenant_id,
        limit=limit,
        current_user=current_user,
        db=db,
    )


@router.get("/llm/training/jobs/{job_id}")
async def get_llm_training_job(
    job_id: str,
    tenant_id: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService

    effective_tenant = tenant_id or current_user.tenant_id
    service = LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR)
    item = await service.get_job(effective_tenant, job_id)
    if item is None:
        return {"exists": False, "job_id": job_id}
    payload = {"exists": True, "item": _serialize_training_job(item)}
    if item.runtime_task_id:
        payload["runtime_task"] = await _get_runtime_task_payload(item.runtime_task_id, tenant_id=effective_tenant, expected_type="llm_training")
        if await service.reconcile_job_runtime_state(item, payload["runtime_task"]):
            await db.commit()
            payload["item"] = _serialize_training_job(item)
    return payload


@router.get("/llm/models")
async def list_llm_models(
    tenant_id: str | None = None,
    limit: int = 50,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService

    effective_tenant = tenant_id or current_user.tenant_id
    service = LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR)
    items = await service.list_models(effective_tenant, limit=max(limit, 1))
    if await service.reconcile_model_registry_states(effective_tenant, items):
        await db.commit()
    active = await service.get_active_model(effective_tenant)
    return {"items": [_serialize_registry_model(item) for item in items], "count": len(items), "tenant_id": effective_tenant, "active": active}


@router.post("/llm/models/{model_id}/activate")
async def activate_llm_model(
    model_id: str,
    tenant_id: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    service = LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR)
    model = await service.activate_model(
        tenant_id=effective_tenant,
        model_id=model_id,
        actor_id=current_user.id,
    )
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_manual_activate",
        "medium",
        f"管理员激活模型: {model.model_name}",
        user_id=current_user.id,
        target=model_id,
        result="ok",
        metadata={"model_id": model_id, "model_name": model.model_name},
    )
    return {"ok": True, "item": _serialize_registry_model(model)}


@router.post("/llm/models/{model_id}/canary")
async def update_llm_model_canary(
    model_id: str,
    canary_percent: int = 0,
    tenant_id: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService

    effective_tenant = tenant_id or current_user.tenant_id
    model = await LLMTrainingService(db, redis_client=get_redis(), reports_dir=REPORTS_DIR).update_model_canary_percent(
        tenant_id=effective_tenant,
        model_id=model_id,
        canary_percent=canary_percent,
        actor_id=current_user.id,
    )
    return {"ok": True, "item": _serialize_registry_model(model)}


@router.get("/llm/models/{model_id}/verify")
async def verify_llm_model_serving(
    model_id: str,
    tenant_id: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    result = await LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR).verify_model_serving(
        tenant_id=effective_tenant,
        model_id=model_id,
    )
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_manual_verify",
        "low" if result.get("ok") else "high",
        "管理员触发模型部署校验",
        user_id=current_user.id,
        target=model_id,
        result="ok" if result.get("ok") else "error",
        metadata={"model_id": model_id, "verify_result": result},
    )
    return {"ok": bool(result.get("ok")), "result": result}


@router.post("/llm/models/{model_id}/publish")
async def publish_llm_model(
    model_id: str,
    tenant_id: str | None = None,
    activate: bool = False,
    verify: bool = True,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    service = LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR)
    publish_result = await service.publish_model_artifact(tenant_id=effective_tenant, model_id=model_id)
    response: dict[str, object] = {"ok": bool(publish_result.get("ok")), "publish_result": publish_result}
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_manual_publish",
        "medium" if publish_result.get("published") else "high",
        str(publish_result.get("message") or "管理员触发模型发布"),
        user_id=current_user.id,
        target=model_id,
        result="ok" if publish_result.get("published") else "warning",
        metadata={"model_id": model_id, "publish_result": publish_result},
    )

    if activate and publish_result.get("publish_ready"):
        model = await service.activate_model(tenant_id=effective_tenant, model_id=model_id, actor_id=current_user.id)
        response["activated_model"] = _serialize_registry_model(model)
        await SecurityAuditService(redis_client, db).log_event(
            effective_tenant,
            "llm_model_manual_activate",
            "medium",
            f"管理员激活模型: {model.model_name}",
            user_id=current_user.id,
            target=model_id,
            result="ok",
            metadata={"model_id": model_id, "model_name": model.model_name, "source": "publish_endpoint"},
        )

    if verify and publish_result.get("published"):
        response["verify_result"] = await service.verify_model_serving(tenant_id=effective_tenant, model_id=model_id)
        response["ok"] = bool(response["verify_result"].get("ok"))  # type: ignore[index]
        await SecurityAuditService(redis_client, db).log_event(
            effective_tenant,
            "llm_model_manual_verify",
            "low" if response["verify_result"].get("ok") else "high",  # type: ignore[index]
            "管理员触发模型部署校验",
            user_id=current_user.id,
            target=model_id,
            result="ok" if response["verify_result"].get("ok") else "error",  # type: ignore[index]
            metadata={"model_id": model_id, "verify_result": response["verify_result"]},
        )

    return response


@router.post("/llm/models/retry-failed-publishes")
async def retry_failed_llm_model_publishes(
    tenant_id: str | None = None,
    limit: int = 10,
    verify: bool = True,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    service = LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR)
    payload = await service.retry_failed_publications(
        tenant_id=effective_tenant,
        limit=max(limit, 1),
        verify=bool(verify),
    )
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_batch_republish",
        "medium",
        f"管理员批量重试模型发布，共尝试 {payload.get('attempted_count', 0)} 个模型",
        user_id=current_user.id,
        result="ok",
        metadata={
            "attempted_count": payload.get("attempted_count", 0),
            "skipped_count": payload.get("skipped_count", 0),
            "models": [item.get("model_id") for item in payload.get("attempted", [])],
        },
    )
    return payload


@router.post("/llm/models/rollback")
async def rollback_llm_model(
    tenant_id: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    result = await LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR).rollback_active_model(
        tenant_id=effective_tenant,
        actor_id=current_user.id,
    )
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_manual_rollback",
        "high",
        "管理员回滚上一版激活模型",
        user_id=current_user.id,
        target=str((result.get("rolled_back_to") or {}).get("model_id") or ""),
        result="warning",
        metadata={"rollback_result": result},
    )
    return result


@router.get("/system/retrieval-metrics")
async def get_retrieval_metrics(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.retrieval_observability_service import RetrievalObservabilityService

    return await RetrievalObservabilityService(get_redis()).summary(current_user.tenant_id)


@router.get("/system/readiness")
async def get_platform_readiness(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.platform_readiness_service import PlatformReadinessService

    return await PlatformReadinessService(db, get_redis()).evaluate(current_user.tenant_id)


@router.get("/system/gap-report")
async def get_delivery_gap_report(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.delivery_gap_service import DeliveryGapService
    from app.services.push_notification_service import PushNotificationService

    redis_client = get_redis()
    report = await DeliveryGapService(db, redis_client).build_report(current_user.tenant_id)
    report["push_runtime_status"] = await PushNotificationService(db, redis_client).get_health_summary(
        tenant_id=current_user.tenant_id
    )
    return report


@router.get("/system/security-policy")
async def get_security_policy(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.security_policy_service import SecurityPolicyService

    return SecurityPolicyService().evaluate()


@router.get("/system/mobile-auth")
async def get_mobile_auth_status(
    request: Request,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mobile_oauth_service import MobileOAuthService

    issuer = str(request.base_url).rstrip("/")
    return {"tenant_id": current_user.tenant_id, **MobileOAuthService(db).status(issuer)}


@router.get("/system/push-notifications")
async def get_push_notification_status(
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.push_notification_service import PushNotificationService

    return await PushNotificationService(db, get_redis()).get_health_summary(tenant_id=current_user.tenant_id)


@router.get("/runtime/tasks")
async def get_runtime_tasks(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.task_store import TaskStore
    from app.config import settings

    store = TaskStore(get_redis(), retention_seconds=settings.runtime_task_retention_seconds)
    tasks = await store.list_tasks(current_user.tenant_id, limit=max(limit, 1), offset=max(offset, 0))
    return {"items": tasks, "total": len(tasks), "limit": max(limit, 1), "offset": max(offset, 0)}


@router.get("/runtime/metrics")
async def get_runtime_metrics_v2(
    limit: int = 200,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.engine import AgentRuntime

    runtime = AgentRuntime(get_redis())
    rows = await runtime.list_metrics(current_user.tenant_id, limit=max(limit, 1))
    redis_client = get_redis()
    counters = await redis_client.hgetall(f"runtime:counters:{current_user.tenant_id}") if redis_client is not None else {}
    if not rows:
        return {
            "items": [],
            "summary": {
                "count": 0,
                "ttft_ms_p95": 0,
                "completion_ms_p95": 0,
                "fallback_rate": 0.0,
                "deny_rate": 0.0,
                "avg_retries": 0.0,
                "avg_tool_calls": 0.0,
                "sse_disconnects": int(counters.get("sse_disconnects", 0) or 0),
            },
        }

    ttft = sorted(int(item.get("ttft_ms", 0) or 0) for item in rows)
    completion = sorted(int(item.get("completion_ms", 0) or 0) for item in rows)
    fallback_sum = sum(int(item.get("fallback_rate", 0) or 0) for item in rows)
    deny_sum = sum(int(item.get("deny_rate", 0) or 0) for item in rows)
    retries_sum = sum(int(item.get("retries", 0) or 0) for item in rows)
    tool_calls_sum = sum(int(item.get("tool_calls", 0) or 0) for item in rows)
    idx = max(int(len(rows) * 0.95) - 1, 0)
    summary = {
        "count": len(rows),
        "ttft_ms_p95": ttft[idx],
        "completion_ms_p95": completion[idx],
        "fallback_rate": round(fallback_sum / max(len(rows), 1), 4),
        "deny_rate": round(deny_sum / max(len(rows), 1), 4),
        "avg_retries": round(retries_sum / max(len(rows), 1), 4),
        "avg_tool_calls": round(tool_calls_sum / max(len(rows), 1), 4),
        "sse_disconnects": int(counters.get("sse_disconnects", 0) or 0),
    }
    return {"items": rows, "summary": summary}


@router.get("/runtime/tool-decisions")
async def get_runtime_tool_decisions(
    limit: int = 100,
    offset: int = 0,
    source: str = "merged",
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.runtime.permission_gate import PermissionGate
    from app.services.security_audit_service import SecurityAuditService

    gate = PermissionGate(get_redis())
    runtime_items = await gate.list_decisions(current_user.tenant_id, limit=max(limit, 1), offset=max(offset, 0))

    if source == "redis":
        return {"items": runtime_items, "total": len(runtime_items), "limit": max(limit, 1), "offset": max(offset, 0), "source": "redis"}

    audit_payload = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=max(limit, 1),
        offset=max(offset, 0),
        action="runtime_tool_decision",
    )
    audit_items = []
    for item in audit_payload.get("events", []):
        metadata = item.get("metadata") or {}
        audit_items.append(
            {
                "decision": item.get("result"),
                "reason": metadata.get("reason") or item.get("message"),
                "source": metadata.get("source") or "security_audit",
                "tool_name": metadata.get("tool_name") or item.get("target"),
                "user_id": item.get("user_id"),
                "tenant_id": item.get("tenant_id"),
                "trace_id": item.get("trace_id"),
                "created_at": item.get("timestamp"),
                "channel": "security_audit",
            }
        )

    if source == "audit":
        return {"items": audit_items, "total": len(audit_items), "limit": max(limit, 1), "offset": max(offset, 0), "source": "audit"}

    merged = runtime_items + audit_items
    merged.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    merged = merged[: max(limit, 1)]
    return {"items": merged, "total": len(merged), "limit": max(limit, 1), "offset": max(offset, 0), "source": "merged"}


@router.get("/runtime/tool-decisions/summary")
async def get_runtime_tool_decisions_summary(
    limit: int = 1000,
    since_hours: int = 24,
    decision: str | None = None,
    tool_name: str | None = None,
    reason: str | None = None,
    source: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.runtime.permission_gate import PermissionGate
    from app.services.security_audit_service import SecurityAuditService

    gate = PermissionGate(get_redis())
    runtime_items = await gate.list_decisions(current_user.tenant_id, limit=max(limit, 1), offset=0)
    audit_payload = await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id,
        limit=max(limit, 1),
        offset=0,
        action="runtime_tool_decision",
    )

    items: list[dict] = []
    items.extend(runtime_items)
    for item in audit_payload.get("events", []):
        metadata = item.get("metadata") or {}
        items.append(
            {
                "decision": item.get("result"),
                "reason": metadata.get("reason") or item.get("message"),
                "source": metadata.get("source") or "security_audit",
                "tool_name": metadata.get("tool_name") or item.get("target"),
                "created_at": item.get("timestamp"),
            }
        )

    def parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).replace(tzinfo=None)
        except ValueError:
            return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since_dt = now
    if since_hours > 0:
        since_dt = now - timedelta(hours=since_hours)

    decision_filter = (decision or "").strip().lower()
    tool_filter = (tool_name or "").strip().lower()
    reason_filter = (reason or "").strip().lower()
    source_filter = (source or "").strip().lower()

    filtered_items = []
    for item in items:
        created_at = parse_iso(str(item.get("created_at") or ""))
        if since_hours > 0 and created_at and created_at < since_dt:
            continue
        item_decision = str(item.get("decision") or "unknown").lower()
        item_tool = str(item.get("tool_name") or "unknown").lower()
        item_reason = str(item.get("reason") or "unknown").lower()
        item_source = str(item.get("source") or "unknown").lower()
        if decision_filter and item_decision != decision_filter:
            continue
        if tool_filter and tool_filter not in item_tool:
            continue
        if reason_filter and reason_filter not in item_reason:
            continue
        if source_filter and item_source != source_filter:
            continue
        filtered_items.append(item)

    decision_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    tool_decision_matrix: dict[str, dict[str, int]] = {}
    reason_decision_matrix: dict[str, dict[str, int]] = {}
    source_counts: dict[str, int] = {}
    trend_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"allow": 0, "ask": 0, "deny": 0, "unknown": 0})
    for item in filtered_items:
        decision = str(item.get("decision") or "unknown")
        tool_name = str(item.get("tool_name") or "unknown")
        reason = str(item.get("reason") or "unknown")
        source = str(item.get("source") or "unknown")
        created_at = parse_iso(str(item.get("created_at") or "")) or now
        bucket = created_at.replace(minute=0, second=0, microsecond=0).isoformat()
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        tool_bucket = tool_decision_matrix.setdefault(tool_name, {})
        tool_bucket[decision] = tool_bucket.get(decision, 0) + 1
        reason_bucket = reason_decision_matrix.setdefault(reason, {})
        reason_bucket[decision] = reason_bucket.get(decision, 0) + 1
        trend_buckets[bucket][decision if decision in {"allow", "ask", "deny"} else "unknown"] += 1

    top_tools = sorted(tool_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    top_reasons = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    matrix_tools = []
    for tool_name, _ in top_tools:
        row = {"tool_name": tool_name}
        row.update(tool_decision_matrix.get(tool_name, {}))
        matrix_tools.append(row)

    matrix_reasons = []
    for reason, _ in top_reasons:
        row = {"reason": reason}
        row.update(reason_decision_matrix.get(reason, {}))
        matrix_reasons.append(row)

    return {
        "total": len(filtered_items),
        "window_hours": since_hours,
        "applied_filters": {
            "decision": decision_filter or None,
            "tool_name": tool_filter or None,
            "reason": reason_filter or None,
            "source": source_filter or None,
        },
        "decision_counts": decision_counts,
        "source_counts": source_counts,
        "top_tools": [{"tool_name": name, "count": count} for name, count in top_tools],
        "top_reasons": [{"reason": name, "count": count} for name, count in top_reasons],
        "matrix_by_tool": matrix_tools,
        "matrix_by_reason": matrix_reasons,
        "trend_by_hour": [{"hour": hour, **counts} for hour, counts in sorted(trend_buckets.items())],
    }


@router.post("/runtime/replay")
async def replay_runtime_trace(
    trace_id: str,
    current_user: User = Depends(require_role("ADMIN")),
):
    from app.agent.runtime.engine import AgentRuntime

    runtime = AgentRuntime(get_redis())
    events = await runtime.replay(trace_id)
    events = [item for item in events if item.get("tenant_id") == current_user.tenant_id]
    return {"trace_id": trace_id, "events": events, "count": len(events)}


@router.get("/runtime/checkpoints")
async def list_runtime_checkpoints(
    session_id: str,
    limit: int = 50,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.agent.runtime.checkpoint_store import RuntimeCheckpointStore

    store = RuntimeCheckpointStore(db)
    rows = await store.list_for_session(session_id, limit=max(limit, 1))
    items = []
    for row in rows:
        if row.tenant_id != current_user.tenant_id:
            continue
        items.append(
            {
                "id": row.id,
                "session_id": row.session_id,
                "trace_id": row.trace_id,
                "tenant_id": row.tenant_id,
                "node_name": row.node_name,
                "iteration": row.iteration,
                "payload_json": row.payload_json,
                "created_at": row.created_at.isoformat(),
            }
        )
    return {"items": items, "count": len(items), "session_id": session_id}


@router.get("/runtime/checkpoints/summary")
async def list_runtime_checkpoint_summary(
    limit: int = 50,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.runtime_checkpoint_service import RuntimeCheckpointService

    items = await RuntimeCheckpointService(db).summarize_sessions(current_user.tenant_id, limit=max(limit, 1))
    return {"items": items, "count": len(items), "limit": max(limit, 1)}


@router.get("/system/retrieval-integrity")
async def get_retrieval_integrity(
    sample_size: int = 12,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.retrieval_integrity_service import RetrievalIntegrityService

    return await RetrievalIntegrityService(db).evaluate(current_user.tenant_id, sample_size=max(sample_size, 1))


@router.post("/evaluation/run")
async def run_evaluation(sample_limit: int = 100, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(db, get_redis(), reports_dir=REPORTS_DIR).run(
        current_user.tenant_id,
        sample_limit=max(sample_limit, 1),
        actor=current_user,
    )


@router.post("/evaluation/run-async")
async def run_evaluation_async(sample_limit: int = 100, current_user: User = Depends(require_role("ADMIN"))):
    from app.evaluation.tasks import run_evaluation_job

    task = run_evaluation_job.apply_async(
        args=(current_user.tenant_id, max(sample_limit, 1), current_user.id),
        queue=settings.celery_maintenance_queue,
    )
    await _seed_runtime_task(task.id, tenant_id=current_user.tenant_id, task_type="evaluation", description=f"评估任务: tenant={current_user.tenant_id}")
    return {"task_id": task.id, "status": "pending", "tenant_id": current_user.tenant_id, "sample_limit": max(sample_limit, 1)}


@router.get("/evaluation/tasks/{task_id}")
async def get_evaluation_task(task_id: str, current_user: User = Depends(require_role("ADMIN"))):
    return await _get_runtime_task_payload(task_id, tenant_id=current_user.tenant_id, expected_type="evaluation")


@router.get("/evaluation/latest")
async def get_latest_evaluation(current_user: User = Depends(require_role("ADMIN"))):
    from app.services.evaluation_service import EvaluationService

    return await EvaluationService(None, get_redis(), reports_dir=REPORTS_DIR).latest(current_user.tenant_id)


@router.get("/evaluation/runtime-metrics")
async def get_runtime_metrics(current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.runtime_evaluation_service import RuntimeEvaluationService

    data = await RuntimeEvaluationService(db, get_redis()).get_metrics(current_user.tenant_id)
    return data


@router.get("/evaluation/runtime-metrics/history")
async def get_runtime_metrics_history(limit: int = 30, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.runtime_evaluation_service import RuntimeEvaluationService

    return await RuntimeEvaluationService(db, get_redis()).get_history(current_user.tenant_id, limit=max(limit, 1))


@router.get("/evaluation/runtime-metrics/export", response_class=PlainTextResponse)
async def export_runtime_metrics(
    format: str = "csv",
    limit: int = 100,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.runtime_evaluation_service import RuntimeEvaluationService

    service = RuntimeEvaluationService(db, get_redis())
    if format == "json":
        payload = await service.get_history(current_user.tenant_id, limit=max(limit, 1))
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return await service.export_csv(current_user.tenant_id, limit=max(limit, 1))


@router.post("/reindex")
async def reindex_documents(limit: int | None = None, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.index_sync_service import IndexSyncService

    return await IndexSyncService(db).reindex_tenant(current_user.tenant_id, limit=limit)
