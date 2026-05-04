"""Admin sub-router: security events, alerts, watermark tracing, backend health."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.rbac import require_role
from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.db.user import User

router = APIRouter()


@router.get("/security/events")
async def get_security_events(
    limit: int = 50, offset: int = 0, severity: str | None = None,
    action: str | None = None, result: str | None = None,
    from_time: str | None = Query(default=None, alias="from"),
    to_time: str | None = Query(default=None, alias="to"),
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService
    def parse_iso(value: str | None) -> datetime | None:
        if not value: return None
        try: return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError: return None
    return await SecurityAuditService(get_redis(), db).list_events(
        current_user.tenant_id, limit=limit, offset=offset, severity=severity,
        action=action, result=result, from_time=parse_iso(from_time), to_time=parse_iso(to_time))


@router.get("/security/alerts")
async def get_security_alerts(limit: int = 50, offset: int = 0, current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.security_audit_service import SecurityAuditService
    return await SecurityAuditService(get_redis(), db).list_alerts(current_user.tenant_id, limit=limit, offset=offset)


@router.get("/security/summary")
async def get_security_summary(
    limit: int = 1000, severity: str | None = None, action: str | None = None,
    result: str | None = None, since_hours: int = 24,
    current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db),
):
    from app.services.security_audit_service import SecurityAuditService
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from_time = now - timedelta(hours=since_hours) if since_hours > 0 else None
    return await SecurityAuditService(get_redis(), db).summarize_events(
        current_user.tenant_id, limit=max(limit, 1), severity=severity,
        action=action, result=result, from_time=from_time, to_time=now)


@router.post("/security/watermark/trace")
async def trace_watermark(text: str | None = None, fingerprint: str | None = None,
    current_user: User = Depends(require_role("ADMIN")), db: AsyncSession = Depends(get_db)):
    from app.services.dlp_forensics_service import DLPForensicsService
    service = DLPForensicsService(get_redis(), db)
    if fingerprint:
        r = await service.trace_by_fingerprint(tenant_id=current_user.tenant_id, fingerprint=fingerprint)
        return {"result": r, "found": bool(r), "mode": "fingerprint"}
    if text:
        r = await service.trace_from_text(tenant_id=current_user.tenant_id, text=text)
        return {"result": r, "found": bool(r and r.get("found", True)), "mode": "text"}
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

    async def run_sync(name, fn, timeout=2.5):
        try:
            r = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
            if isinstance(r, dict): r.setdefault("available", True)
            return name, r
        except Exception as exc: return name, {"available": False, "status": "degraded", "error": str(exc)}

    async def run_async(name, coro, timeout=2.5):
        try:
            r = await asyncio.wait_for(coro, timeout=timeout)
            if isinstance(r, dict): r.setdefault("available", True)
            return name, r
        except Exception as exc: return name, {"available": False, "status": "degraded", "error": str(exc)}

    def neo4j_health():
        c = Neo4jClient()
        try: return c.health()
        finally: c.close()

    checks = await asyncio.gather(
        run_sync("elasticsearch", lambda: ESClient().health()),
        run_sync("milvus", lambda: MilvusClient().health()),
        run_sync("neo4j", neo4j_health),
        run_sync("clamav", lambda: FileScanner().health()),
        run_async("llm", LLMService().health()),
        run_async("guardrails", GuardrailsService().health()),
    )
    payload = {name: result for name, result in checks}
    payload["redis"] = {"available": get_redis() is not None}
    payload["pii"] = {"available": bool(settings.pii_masking_enabled), "presidio_enabled": bool(settings.pii_presidio_enabled), "mode": "presidio_patterns" if PIIMasker()._recognizers else "local_regex"}
    payload["runtime"] = {"mode": "v2_only"}
    return payload
