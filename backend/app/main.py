"""DocMind Agent FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import time
import uuid
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
import structlog
from sqlalchemy import text

from app.config import settings
from app.observability.logging import setup_logging
from app.observability.metrics import metrics_registry


async def _measure_startup_phase(app: FastAPI, name: str, action):
    started = time.perf_counter()
    try:
        return await action()
    finally:
        duration = time.perf_counter() - started
        timings = getattr(app.state, "startup_timings", {})
        timings[name] = round(duration, 6)
        app.state.startup_timings = timings
        metrics_registry.record_startup_phase(name, duration)
        metrics_registry.record_operation(f"startup.{name}", duration)


async def _recover_runtime_tasks(logger) -> None:
    from app.agent.runtime.task_store import TaskStore
    from app.dependencies import get_redis

    redis_client = get_redis()
    if redis_client is None:
        return
    recovered = await TaskStore(redis_client, retention_seconds=settings.runtime_task_retention_seconds).recover_stuck_running(
        settings.runtime_stage_timeout_seconds
    )
    if recovered:
        logger.warning("startup.runtime_tasks_recovered", recovered=recovered)


async def _warm_ai_health(app: FastAPI, logger) -> None:
    ai_health = await refresh_ai_health(app, force=True)
    llm_health = ai_health["llm"]
    embedding_health = ai_health["embedding"]
    if not llm_health.get("available"):
        logger.warning("startup.llm_unavailable", detail=llm_health)
    if not embedding_health.get("available"):
        logger.warning("startup.embedding_unavailable", detail=embedding_health)


async def refresh_ai_health(app: FastAPI, *, force: bool = False) -> dict:
    """Refresh AI health with a short TTL so /health reflects runtime recovery."""
    cached = getattr(app.state, "ai_health", None)
    checked_at = getattr(app.state, "ai_health_checked_at", None)
    if not force and cached and checked_at:
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        if age < 15:
            return cached

    from app.ingestion.embedder import DocumentEmbedder
    from app.services.llm_service import LLMService

    llm_health, embedding_health = await asyncio.gather(
        LLMService().health(),
        asyncio.to_thread(DocumentEmbedder().remote_health),
    )
    payload = {
        "llm": llm_health,
        "embedding": embedding_health,
        "llm_available": bool(llm_health.get("available")),
        "embedding_available": bool(embedding_health.get("available")),
    }
    app.state.ai_health = payload
    app.state.ai_health_checked_at = datetime.now(timezone.utc)
    return payload


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    setup_logging()
    logger = structlog.get_logger("docmind.startup")
    logger.info("startup.begin", service=settings.app_name, environment=settings.app_env)

    from app.dependencies import (
        ensure_row_level_security,
        ensure_startup_schema_compatibility,
        init_db,
        init_redis,
        init_minio,
        init_milvus,
        init_elasticsearch,
        get_session_factory,
    )
    app.state.startup_timings = {}
    startup_started = time.perf_counter()
    await _measure_startup_phase(app, "db_init", lambda: init_db(app))
    await _measure_startup_phase(app, "redis_init", lambda: init_redis(app))
    await _measure_startup_phase(app, "minio_init", lambda: init_minio(app))
    await _measure_startup_phase(app, "milvus_init", lambda: init_milvus(app))
    await _measure_startup_phase(app, "elasticsearch_init", lambda: init_elasticsearch(app))
    app.state.ai_health_task = asyncio.create_task(_warm_ai_health(app, logger))
    app.state.runtime_recovery_task = asyncio.create_task(_recover_runtime_tasks(logger))

    if settings.app_auto_create_tables:
        from app.models import Base  # noqa: F401
        from app.dependencies import get_engine
        await _measure_startup_phase(app, "db_schema_prepare", lambda: _prepare_schema(get_engine(), Base))
        await _measure_startup_phase(app, "db_schema_compatibility", ensure_startup_schema_compatibility)
        await _measure_startup_phase(app, "db_row_level_security", ensure_row_level_security)
        from app.bootstrap import ensure_bootstrap_state

        await _measure_startup_phase(app, "bootstrap_state", lambda: ensure_bootstrap_state(get_session_factory()))

    total_duration = time.perf_counter() - startup_started
    app.state.startup_timings["total"] = round(total_duration, 6)
    metrics_registry.record_startup_phase("total", total_duration)
    metrics_registry.record_operation("startup.total", total_duration)

    logger.info("startup.ready")

    yield

    from app.dependencies import close_db, close_redis, close_elasticsearch
    ai_health_task = getattr(app.state, "ai_health_task", None)
    if ai_health_task is not None and not ai_health_task.done():
        ai_health_task.cancel()
    runtime_recovery_task = getattr(app.state, "runtime_recovery_task", None)
    if runtime_recovery_task is not None and not runtime_recovery_task.done():
        runtime_recovery_task.cancel()
    await close_db(app)
    await close_redis(app)
    await close_elasticsearch(app)
    structlog.get_logger("docmind.shutdown").info("shutdown.complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered intelligent agent for corporate document management",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # --- CORS Middleware ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        start = time.perf_counter()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        response = await call_next(request)
        duration = time.perf_counter() - start
        duration_ms = duration * 1000
        path = request.url.path
        slow_threshold_ms = settings.slow_admin_request_threshold_ms if path.startswith("/api/v1/admin") else settings.slow_request_threshold_ms
        is_slow = duration_ms >= slow_threshold_ms
        metrics_registry.record_request(request.method, path, response.status_code, duration, slow=is_slow)
        metrics_registry.record_operation(f"http.{request.method}.{path}", duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        response.headers["Server-Timing"] = f'app;dur={duration_ms:.1f}'
        if is_slow:
            structlog.get_logger("docmind.http").warning(
                "http.request_slow",
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
                threshold_ms=slow_threshold_ms,
                request_id=request_id,
            )
        return response

    from app.api.v1 import admin, auth, chat, documents, notifications, search
    from app.api.v1 import ws_chat
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
    app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
    app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
    app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
    app.include_router(search.router, prefix="/api/v1/search", tags=["Search"])
    app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
    app.include_router(ws_chat.router, prefix="/api/v1", tags=["WebSocket Chat"])

    @app.get("/health", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.app_name,
            "environment": settings.app_env,
            "startup_complete": True,
            "startup_timings": getattr(app.state, "startup_timings", {}),
        }

    @app.get("/ready", tags=["System"])
    async def readiness_check():
        started = time.perf_counter()
        ai_health = await refresh_ai_health(app)
        duration = time.perf_counter() - started
        metrics_registry.record_operation("system.ready", duration)
        ready = bool(ai_health.get("llm_available", False) and ai_health.get("embedding_available", False))
        return {
            "status": "ready" if ready else "degraded",
            "service": settings.app_name,
            "environment": settings.app_env,
            "llm_available": bool(ai_health.get("llm_available", False)),
            "embedding_available": bool(ai_health.get("embedding_available", False)),
            "startup_timings": getattr(app.state, "startup_timings", {}),
            "ai": {
                "llm": ai_health.get("llm", {}),
                "embedding": ai_health.get("embedding", {}),
            },
        }

    if settings.app_metrics_enabled:
        @app.get("/metrics", tags=["System"], response_class=PlainTextResponse)
        async def metrics():
            return metrics_registry.render_prometheus()

    return app


# Application instance
app = create_app()


async def _prepare_schema(engine, base) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(2026042801)"))
        try:
            await conn.run_sync(base.metadata.create_all)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(2026042801)"))
