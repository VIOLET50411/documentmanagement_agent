"""Admin sub-router: LLM config, corpus export, training jobs, model registry."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.db.user import User

from app.api.v1.admin._helpers import (
    REPORTS_DIR, PUBLIC_DATASETS_DIR,
    _serialize_training_job, _serialize_registry_model,
    _seed_runtime_task, _get_runtime_task_payload,
)

router = APIRouter()

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
        description=f"公开语料导出任务: dataset={dataset_name}, tenant={tenant_id}",
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
        f"管理员激活模型 {model.model_name}",
        user_id=current_user.id,
        target=model_id,
        result="ok",
        metadata={"model_id": model_id, "model_name": model.model_name},
    )
    return {"ok": True, "item": _serialize_registry_model(model)}


@router.post("/llm/models/{model_id}/approve")
async def approve_llm_model(
    model_id: str,
    tenant_id: str | None = None,
    reason: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    service = LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR)
    approval = await service.record_model_approval(
        tenant_id=effective_tenant,
        model_id=model_id,
        approved=True,
        actor_id=current_user.id,
        reason=reason,
    )
    model = await service.get_model(effective_tenant, model_id)
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_manual_approve",
        "medium",
        f"管理员审批通过模型 {model_id}",
        user_id=current_user.id,
        target=model_id,
        result="ok",
        metadata={"model_id": model_id, "approval": approval},
    )
    return {"ok": True, "approval": approval, "item": _serialize_registry_model(model)}


@router.post("/llm/models/{model_id}/reject")
async def reject_llm_model(
    model_id: str,
    tenant_id: str | None = None,
    reason: str | None = None,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    service = LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR)
    approval = await service.record_model_approval(
        tenant_id=effective_tenant,
        model_id=model_id,
        approved=False,
        actor_id=current_user.id,
        reason=reason,
    )
    model = await service.get_model(effective_tenant, model_id)
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_manual_reject",
        "high",
        f"管理员拒绝模型 {model_id} 激活",
        user_id=current_user.id,
        target=model_id,
        result="warning",
        metadata={"model_id": model_id, "approval": approval},
    )
    return {"ok": True, "approval": approval, "item": _serialize_registry_model(model)}


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

    verify_before_activate = bool(verify) or (bool(activate) and bool(settings.llm_training_deploy_verify_enabled))
    if verify_before_activate and publish_result.get("published"):
        response["verify_result"] = await service.verify_model_serving(tenant_id=effective_tenant, model_id=model_id)
        response["ok"] = bool(response["verify_result"].get("ok"))  # type: ignore[index]
        await SecurityAuditService(redis_client, db).log_event(
            effective_tenant,
            "llm_model_manual_verify",
            "low" if response["verify_result"].get("ok") else "high",  # type: ignore[index]
            "admin triggered model deployment verification",
            user_id=current_user.id,
            target=model_id,
            result="ok" if response["verify_result"].get("ok") else "error",  # type: ignore[index]
            metadata={"model_id": model_id, "verify_result": response["verify_result"]},
        )

    if activate and publish_result.get("publish_ready"):
        verify_ok = True
        if settings.llm_training_deploy_verify_enabled:
            verify_payload = response.get("verify_result") if isinstance(response.get("verify_result"), dict) else {}
            verify_ok = bool(verify_payload.get("ok"))
        if verify_ok:
            model = await service.activate_model(tenant_id=effective_tenant, model_id=model_id, actor_id=current_user.id)
            response["activated_model"] = _serialize_registry_model(model)
            await SecurityAuditService(redis_client, db).log_event(
                effective_tenant,
                "llm_model_manual_activate",
                "medium",
                f"admin activated model {model.model_name}",
                user_id=current_user.id,
                target=model_id,
                result="ok",
                metadata={"model_id": model_id, "model_name": model.model_name, "source": "publish_endpoint"},
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


@router.post("/llm/models/retire-nonrecoverable")
async def retire_nonrecoverable_llm_models(
    tenant_id: str | None = None,
    limit: int = 20,
    dry_run: bool = True,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    effective_tenant = tenant_id or current_user.tenant_id
    redis_client = get_redis()
    service = LLMTrainingService(db, redis_client=redis_client, reports_dir=REPORTS_DIR)
    models = await service.list_models(effective_tenant, limit=max(limit * 5, 20))
    changed = await service.reconcile_model_registry_states(effective_tenant, models)
    payload = await service.retire_nonrecoverable_models(
        tenant_id=effective_tenant,
        limit=max(limit, 1),
        dry_run=bool(dry_run),
        actor_id=current_user.id,
    )
    if changed or payload.get("changed_count", 0):
        await db.commit()
    await SecurityAuditService(redis_client, db).log_event(
        effective_tenant,
        "llm_model_retire_nonrecoverable",
        "medium" if dry_run else "high",
        (
            f"管理员{'预演' if dry_run else '执行'}历史不可恢复失败模型退役，"
            f"命中 {payload.get('retired_count', 0)} 个模型"
        ),
        user_id=current_user.id,
        result="warning" if dry_run else "ok",
        metadata={
            "dry_run": bool(dry_run),
            "limit": max(limit, 1),
            "retired_count": payload.get("retired_count", 0),
            "changed_count": payload.get("changed_count", 0),
            "skipped_count": payload.get("skipped_count", 0),
            "model_ids": [item.get("model_id") for item in payload.get("retired", [])],
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

