"""DocMind Agent dependency and runtime resource wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional

from fastapi import Request
from elasticsearch import AsyncElasticsearch
from elasticsearch import TransportError
from minio import Minio
from minio.error import S3Error
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from redis.asyncio import Redis
from redis.exceptions import RedisError
import structlog

from app.config import settings


@dataclass
class ResourceRegistry:
    app: Any = None


_resources = ResourceRegistry()
STARTUP_SCHEMA_COMPATIBILITY_STATEMENTS = (
    "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS invited_by_id VARCHAR(36)",
    "ALTER TABLE IF EXISTS user_invitations ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMP NULL",
    "CREATE INDEX IF NOT EXISTS idx_push_devices_tenant_user_active ON push_devices (tenant_id, user_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_llm_training_jobs_tenant_status ON llm_training_jobs (tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_llm_model_registry_tenant_active ON llm_model_registry (tenant_id, is_active)",
)


@event.listens_for(Session, "after_flush")
def _mark_session_has_writes(session: Session, _flush_context) -> None:
    session.info["has_writes"] = True


def _remember_app(app) -> None:
    if app is not None:
        _resources.app = app


def _write_app_state(app, **values) -> None:
    """Persist initialized resources into app.state."""
    if app is None:
        return
    _remember_app(app)
    for key, value in values.items():
        setattr(app.state, key, value)


def _get_app(request: Request | None = None):
    if request is not None:
        return request.app
    return _resources.app


def _read_app_state(request: Request | None, key: str, fallback=None):
    app = _get_app(request)
    if app is None:
        return fallback
    state = getattr(app, "state", None)
    return getattr(state, key, fallback)


async def init_db(app=None):
    """Initialize async PostgreSQL connection pool."""
    engine = create_async_engine(
        settings.postgres_dsn,
        echo=settings.app_debug,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_timeout=settings.postgres_pool_timeout_seconds,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    _write_app_state(app, db_engine=engine, session_factory=session_factory)


async def close_db(app=None):
    """Close database engine."""
    engine = _read_app_state(None, "db_engine")
    if engine:
        await engine.dispose()
    _write_app_state(app or _resources.app, db_engine=None, session_factory=None)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    session_factory = _read_app_state(request, "session_factory")
    if session_factory is None:
        raise RuntimeError("Database session factory is not initialized.")
    async with session_factory() as session:
        session.info["has_writes"] = False
        try:
            yield session
            has_writes = bool(session.info.get("has_writes")) or bool(session.new or session.dirty or session.deleted)
            if has_writes:
                await session.commit()
            elif session.in_transaction():
                await session.rollback()
        except BaseException:
            if session.in_transaction():
                await session.rollback()
            raise


async def init_redis(app=None):
    """Initialize async Redis connection."""
    logger = structlog.get_logger("docmind.dependencies")
    redis_client = Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=settings.redis_health_check_interval_seconds,
        retry_on_timeout=False,
    )
    try:
        await redis_client.ping()
    except (RedisError, OSError, RuntimeError, ValueError) as exc:
        logger.warning(
            "redis.init_failed",
            url=settings.redis_url,
            error=str(exc),
            connect_timeout_seconds=settings.redis_socket_connect_timeout_seconds,
            socket_timeout_seconds=settings.redis_socket_timeout_seconds,
        )
        await redis_client.aclose()
        redis_client = None
    _write_app_state(app, redis=redis_client)


async def close_redis(app=None):
    """Close Redis connection."""
    redis_client = _read_app_state(None, "redis")
    if redis_client:
        await redis_client.aclose()
    _write_app_state(app or _resources.app, redis=None)


def get_redis(request: Request | None = None) -> Redis | None:
    """Get Redis client instance."""
    return _read_app_state(request, "redis")


def get_engine(request: Request | None = None):
    engine = _read_app_state(request, "db_engine")
    if engine is None:
        raise RuntimeError("Database engine is not initialized.")
    return engine


def get_session_factory(request: Request | None = None):
    session_factory = _read_app_state(request, "session_factory")
    if session_factory is None:
        raise RuntimeError("Database session factory is not initialized.")
    return session_factory


async def init_milvus(app=None):
    """Initialize Milvus connection."""
    try:
        from pymilvus import connections
        from pymilvus.exceptions import MilvusException

        connections.connect(
            alias="default",
            host=settings.milvus_host,
            port=settings.milvus_port,
        )
        milvus_ready = True
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        milvus_ready = False
        structlog.get_logger("docmind.dependencies").warning(
            "milvus.init_failed",
            host=settings.milvus_host,
            port=settings.milvus_port,
            error=str(exc),
        )
    except MilvusException as exc:
        milvus_ready = False
        structlog.get_logger("docmind.dependencies").warning(
            "milvus.init_failed",
            host=settings.milvus_host,
            port=settings.milvus_port,
            error=str(exc),
        )
    _write_app_state(app, milvus_ready=milvus_ready)


async def init_elasticsearch(app=None):
    """Initialize Elasticsearch client without blocking startup on connectivity probes."""
    try:
        es_client = AsyncElasticsearch(hosts=[settings.es_url], request_timeout=5)
    except (TransportError, OSError, RuntimeError, ValueError) as exc:
        structlog.get_logger("docmind.dependencies").warning(
            "elasticsearch.init_failed",
            url=settings.es_url,
            error=str(exc),
        )
        es_client = None
    _write_app_state(app, elasticsearch=es_client)


async def close_elasticsearch(app=None):
    es_client = _read_app_state(None, "elasticsearch")
    if es_client is not None:
        await es_client.close()
    _write_app_state(app or _resources.app, elasticsearch=None)


def get_elasticsearch(request: Request | None = None) -> AsyncElasticsearch:
    es_client = _read_app_state(request, "elasticsearch")
    if es_client is None:
        raise RuntimeError("Elasticsearch client is not initialized.")
    return es_client


async def init_minio(app=None) -> None:
    """Initialize MinIO client without blocking startup on bucket checks."""
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    _write_app_state(app, minio_client=client)


async def set_db_tenant(db: AsyncSession, tenant_id: str) -> None:
    """
    Set current tenant in PostgreSQL session for RLS policies.
    """
    await db.execute(
        text("select set_config('app.current_tenant', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


async def ensure_row_level_security() -> None:
    """Enable PostgreSQL RLS policies for tenant-scoped tables."""
    engine = get_engine()
    statements = [
        "ALTER TABLE documents ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_documents ON documents",
        """
        CREATE POLICY tenant_isolation_documents ON documents
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_document_chunks ON document_chunks",
        """
        CREATE POLICY tenant_isolation_document_chunks ON document_chunks
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_chat_sessions ON chat_sessions",
        """
        CREATE POLICY tenant_isolation_chat_sessions ON chat_sessions
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE feedback ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_feedback ON feedback",
        """
        CREATE POLICY tenant_isolation_feedback ON feedback
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE security_audit_events ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_security_audit_events ON security_audit_events",
        """
        CREATE POLICY tenant_isolation_security_audit_events ON security_audit_events
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE user_memory ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_user_memory ON user_memory",
        """
        CREATE POLICY tenant_isolation_user_memory ON user_memory
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE push_devices ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_push_devices ON push_devices",
        """
        CREATE POLICY tenant_isolation_push_devices ON push_devices
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE llm_training_jobs ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_llm_training_jobs ON llm_training_jobs",
        """
        CREATE POLICY tenant_isolation_llm_training_jobs ON llm_training_jobs
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
        "ALTER TABLE llm_model_registry ENABLE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_isolation_llm_model_registry ON llm_model_registry",
        """
        CREATE POLICY tenant_isolation_llm_model_registry ON llm_model_registry
        USING (tenant_id = current_setting('app.current_tenant', true))
        """,
    ]
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))


async def ensure_startup_schema_compatibility() -> None:
    """Apply idempotent schema patches for drifted local databases."""
    engine = get_engine()
    async with engine.begin() as conn:
        for statement in STARTUP_SCHEMA_COMPATIBILITY_STATEMENTS:
            await conn.execute(text(statement))


def get_minio_client(request: Request | None = None) -> Minio:
    """Get or create MinIO client."""
    client = _read_app_state(request, "minio_client")
    if client is None:
        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        try:
            if not client.bucket_exists(settings.minio_bucket):
                client.make_bucket(settings.minio_bucket)
        except S3Error as exc:
            raise RuntimeError(f"MinIO client initialization failed: {exc}") from exc
        _write_app_state(_resources.app, minio_client=client)
    return client
