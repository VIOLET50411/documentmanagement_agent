from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.api.middleware.auth import get_current_user
from app.main import app
from app.services.auth_service import AuthService
from app.services.mobile_oauth_service import MobileOAuthService


class DummyDB:
    def __init__(self, *, scalar_value=None, execute_value=None):
        self.scalar_value = scalar_value
        self.execute_value = execute_value

    async def execute(self, *_args, **_kwargs):
        return self.execute_value

    async def scalar(self, *_args, **_kwargs):
        return self.scalar_value

    async def flush(self):
        return None

    def add(self, item):
        if getattr(item, "id", None) is None:
            item.id = str(uuid.uuid4())
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class FakeRedis:
    def __init__(self):
        self.counters: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}

    async def incr(self, key: str) -> int:
        current = self.counters.get(key, 0) + 1
        self.counters[key] = current
        return current

    async def hset(self, key: str, mapping: dict[str, str]):
        self.hashes.setdefault(key, {}).update(mapping)
        return True

    async def hgetall(self, key: str):
        return self.hashes.get(key, {})

    async def expire(self, _key: str, _ttl: int):
        return True

    async def ltrim(self, key: str, start: int, end: int):
        rows = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        self.lists[key] = rows[start:stop]
        return True

    async def rpush(self, key: str, value: str):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def llen(self, key: str):
        return len(self.lists.get(key, []))

    async def lrange(self, key: str, start: int, end: int):
        rows = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        return rows[start:stop]

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        return True

    async def zadd(self, key: str, mapping: dict[str, float]):
        self.values[key] = json.dumps(mapping)
        return True

    async def sadd(self, key: str, *values: str):
        bucket = set(json.loads(self.values.get(key, "[]")))
        bucket.update(values)
        self.values[key] = json.dumps(sorted(bucket))
        return len(values)

    async def scard(self, key: str):
        return len(json.loads(self.values.get(key, "[]")))

    async def delete(self, key: str):
        self.hashes.pop(key, None)
        self.lists.pop(key, None)
        self.values.pop(key, None)
        return True


@pytest.fixture
def test_app():
    original_overrides = app.dependency_overrides.copy()
    yield app
    app.dependency_overrides = original_overrides


@pytest_asyncio.fixture
async def api_client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_health_route_returns_payload(api_client: AsyncClient):
    response = await api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert "llm_available" in payload
    assert "embedding_available" in payload


@pytest.mark.asyncio
async def test_login_route_returns_tokens(api_client: AsyncClient, monkeypatch):
    async def fake_authenticate(self, username: str, password: str):
        assert username == "admin_demo"
        assert password == "Password123"
        return SimpleNamespace(id="user-1", tenant_id="tenant-1", role="ADMIN")

    def fake_create_tokens(self, user):
        assert user.id == "user-1"
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "token_type": "bearer",
            "expires_in": 3600,
        }

    monkeypatch.setattr(AuthService, "authenticate", fake_authenticate)
    monkeypatch.setattr(AuthService, "create_tokens", fake_create_tokens)

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db

    app.dependency_overrides[get_db] = override_db

    response = await api_client.post(
        "/api/v1/auth/login",
        json={"username": "admin_demo", "password": "Password123"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-token"


@pytest.mark.asyncio
async def test_me_route_uses_dependency_override(api_client: AsyncClient):
    now = datetime.now(timezone.utc)
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=now,
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB(scalar_value=current_user)

    from app.dependencies import get_db

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    response = await api_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "admin_demo"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["email_verified"] is True


@pytest.mark.asyncio
async def test_chat_replay_route_streams_cached_events(api_client: AsyncClient, monkeypatch):
    fake_redis = FakeRedis()
    trace_id = "trace-1"
    fake_redis.lists[f"runtime:replay:{trace_id}"] = [
        json.dumps(
            {
                "tenant_id": "tenant-1",
                "status": "thinking",
                "sequence_num": 1,
                "trace_id": trace_id,
                "event_id": "evt-1",
                "source": "chat_api",
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "tenant_id": "tenant-1",
                "status": "done",
                "sequence_num": 2,
                "trace_id": trace_id,
                "event_id": "evt-2",
                "source": "chat_api",
            },
            ensure_ascii=False,
        ),
    ]

    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db
    from app.api.v1 import chat as chat_module
    from app.api.middleware import rate_limit as rate_limit_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(chat_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: fake_redis)

    async with api_client.stream(
        "POST",
        f"/api/v1/chat/stream?resume_trace_id={trace_id}&last_sequence=0",
        json={"message": "\u6062\u590d\u4f1a\u8bdd", "search_type": "hybrid"},
    ) as response:
        assert response.status_code == 200
        body = ""
        async for chunk in response.aiter_text():
            body += chunk

    assert '"status": "thinking"' in body
    assert '"status": "done"' in body


@pytest.mark.asyncio
async def test_chat_replay_route_falls_back_to_checkpoint_resume(api_client: AsyncClient, monkeypatch):
    fake_redis = FakeRedis()
    trace_id = "trace-resume"

    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    class DummyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB(execute_value=DummyResult())

    class DummyRuntime:
        def __init__(self, _redis):
            pass

        async def resume_from_checkpoint(self, _request, *, trace_id, db, current_user):
            assert trace_id == "trace-resume"
            assert current_user.tenant_id == "tenant-1"
            yield {
                "status": "reading",
                "trace_id": trace_id,
                "event_id": "evt-r1",
                "sequence_num": 1,
                "source": "agent_runtime_v2_resume",
                "msg": "已从检查点恢复",
            }
            yield {
                "status": "done",
                "trace_id": trace_id,
                "event_id": "evt-r2",
                "sequence_num": 2,
                "source": "agent_runtime_v2_resume",
                "answer": "resume ok",
                "citations": [],
                "agent_used": "resume",
            }

    from app.dependencies import get_db
    from app.api.v1 import chat as chat_module
    from app.api.middleware import rate_limit as rate_limit_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(chat_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.agent.runtime.AgentRuntime", DummyRuntime)

    async with api_client.stream(
        "POST",
        f"/api/v1/chat/stream?resume_trace_id={trace_id}&last_sequence=0",
        json={"message": "恢复会话", "thread_id": "thread-1", "search_type": "hybrid"},
    ) as response:
        assert response.status_code == 200
        body = ""
        async for chunk in response.aiter_text():
            body += chunk

    assert '"status": "reading"' in body
    assert '"resume ok"' in body


@pytest.mark.asyncio
async def test_documents_upload_route_returns_queued_document(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    async def fake_store_and_enqueue(self, **kwargs):
        return {
            "id": kwargs["doc_id"],
            "title": "policy.pdf",
            "file_name": "policy.pdf",
            "file_type": "application/pdf",
            "status": "queued",
            "task_id": "task-1",
            "percentage": 0,
            "file_size": 12,
            "department": kwargs["department"],
            "access_level": kwargs["access_level"],
            "chunk_count": 0,
            "error_message": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    from app.dependencies import get_db
    from app.api.v1 import documents as documents_module
    from app.api.middleware import rate_limit as rate_limit_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.services.document_service.DocumentService.store_and_enqueue", fake_store_and_enqueue)
    monkeypatch.setattr("app.security.file_scanner.FileScanner.scan_bytes", lambda self, content: {"safe": True, "reason": "ok", "engine": "test"})
    monkeypatch.setattr(documents_module, "get_minio_client", lambda: object())
    monkeypatch.setattr(documents_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: fake_redis)

    response = await api_client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy.pdf", b"%PDF-1.4 test", "application/pdf")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["file_name"] == "policy.pdf"


@pytest.mark.asyncio
async def test_documents_list_route_returns_documents(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    async def fake_list_documents(self, **kwargs):
        return {
            "documents": [
                {
                    "id": "doc-1",
                    "title": "\u5236\u5ea6.pdf",
                    "file_name": "\u5236\u5ea6.pdf",
                    "file_type": "application/pdf",
                    "status": "ready",
                    "task_id": "task-1",
                    "percentage": 100,
                    "file_size": 1024,
                    "department": "operations",
                    "access_level": 2,
                    "chunk_count": 4,
                    "error_message": None,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            ],
            "total": 1,
            "page": kwargs["page"],
            "size": kwargs["size"],
        }

    from app.dependencies import get_db
    from app.api.v1 import documents as documents_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.services.document_service.DocumentService.list_documents", fake_list_documents)
    monkeypatch.setattr(documents_module, "get_minio_client", lambda: object())

    response = await api_client.get("/api/v1/documents/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["documents"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_document_status_route_reads_progress_cache(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    document = SimpleNamespace(
        id="doc-1",
        tenant_id="tenant-1",
        status="queued",
        chunk_count=0,
        error_message=None,
        updated_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()
    fake_redis.hashes["doc_progress:doc-1"] = {
        "status": "indexing",
        "percentage": "88",
        "task_id": "task-1",
        "attempt": "1",
        "detail": "\u6b63\u5728\u540c\u6b65\u68c0\u7d22\u7d22\u5f15",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB(scalar_value=document)

    from app.dependencies import get_db
    from app.api.v1 import documents as documents_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(documents_module, "get_redis", lambda: fake_redis)

    response = await api_client.get("/api/v1/documents/doc-1/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "indexing"
    assert payload["percentage"] == 88
    assert payload["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_document_retry_route_returns_task_info(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    async def fake_enqueue_retry(self, **kwargs):
        return {"doc_id": kwargs["doc_id"], "task_id": "retry-task-1", "status": "queued"}

    from app.dependencies import get_db
    from app.api.v1 import documents as documents_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.services.document_service.DocumentService.enqueue_retry", fake_enqueue_retry)
    monkeypatch.setattr(documents_module, "get_minio_client", lambda: object())

    response = await api_client.post("/api/v1/documents/doc-1/retry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["doc_id"] == "doc-1"
    assert payload["task_id"] == "retry-task-1"


@pytest.mark.asyncio
async def test_notifications_routes_register_and_list_devices(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    async def fake_register(self, **kwargs):
        return SimpleNamespace(
            id="device-1",
            tenant_id=kwargs["tenant_id"],
            user_id=kwargs["user_id"],
            platform=kwargs["platform"],
            device_token=kwargs["device_token"],
            device_name=kwargs["device_name"],
            app_version=kwargs["app_version"],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )

    async def fake_list(self, **kwargs):
        return [
            SimpleNamespace(
                id="device-1",
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                platform="android",
                device_token="token-12345678",
                device_name="Pixel",
                app_version="1.0.0",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
        ]

    async def fake_log_event(self, *args, **kwargs):
        return None

    from app.dependencies import get_db
    from app.api.v1 import notifications as notifications_module
    from app.services.push_notification_service import PushNotificationService
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(notifications_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(PushNotificationService, "register_device", fake_register)
    monkeypatch.setattr(PushNotificationService, "list_devices", fake_list)
    monkeypatch.setattr(SecurityAuditService, "log_event", fake_log_event)

    register_response = await api_client.post(
        "/api/v1/notifications/devices",
        json={
            "platform": "android",
            "device_token": "token-12345678",
            "device_name": "Pixel",
            "app_version": "1.0.0",
        },
    )

    assert register_response.status_code == 200
    assert register_response.json()["platform"] == "android"

    list_response = await api_client.get("/api/v1/notifications/devices")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["device_name"] == "Pixel"


@pytest.mark.asyncio
async def test_notifications_events_route_returns_recent_events(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    async def fake_list_recent_events(self, **kwargs):
        return [
            {
                "tenant_id": kwargs["tenant_id"],
                "user_id": kwargs["user_id"],
                "document_id": "doc-1",
                "title": "文档处理状态更新",
                "body": "文档《制度.pdf》当前状态：ready",
                "status": "ready",
                "devices": [{"platform": "android", "device_name": "Pixel"}],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]

    from app.dependencies import get_db
    from app.api.v1 import notifications as notifications_module
    from app.services.push_notification_service import PushNotificationService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(notifications_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(PushNotificationService, "list_recent_events", fake_list_recent_events)

    response = await api_client.get("/api/v1/notifications/events?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 5
    assert payload["items"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_mobile_openid_configuration_route_returns_expected_endpoints(api_client: AsyncClient, monkeypatch):
    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db

    app.dependency_overrides[get_db] = override_db

    response = await api_client.get("/api/v1/auth/mobile/.well-known/openid-configuration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authorization_endpoint"].endswith("/api/v1/auth/mobile/authorize")
    assert payload["token_endpoint"].endswith("/api/v1/auth/mobile/token")
    assert payload["userinfo_endpoint"].endswith("/api/v1/auth/mobile/userinfo")


@pytest.mark.asyncio
async def test_mobile_bootstrap_route_returns_runtime_endpoints(api_client: AsyncClient, monkeypatch):
    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db

    app.dependency_overrides[get_db] = override_db

    response = await api_client.get("/api/v1/auth/mobile/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_base"].endswith("/api/v1")
    assert payload["ws_base"].endswith("/api/v1/ws/chat")
    assert payload["endpoints"]["chat_message"].endswith("/api/v1/chat/message")
    assert payload["auth"]["discovery"]["authorization_endpoint"].endswith("/api/v1/auth/mobile/authorize")


@pytest.mark.asyncio
async def test_mobile_authorize_and_token_routes(api_client: AsyncClient, monkeypatch):
    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db

    app.dependency_overrides[get_db] = override_db

    async def fake_authorize(self, **kwargs):
        return SimpleNamespace(
            code="auth-code-1234567890",
            expires_at=datetime.now(timezone.utc),
            redirect_uri=kwargs["redirect_uri"],
        )

    async def fake_exchange_code(self, **kwargs):
        assert kwargs["code"] == "auth-code-1234567890"
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "token_type": "bearer",
            "expires_in": 1800,
            "id_token": "id-token-1",
            "scope": "openid profile email offline_access",
        }

    monkeypatch.setattr(MobileOAuthService, "authorize", fake_authorize)
    monkeypatch.setattr(MobileOAuthService, "exchange_code", fake_exchange_code)

    authorize_response = await api_client.post(
        "/api/v1/auth/mobile/authorize",
        json={
            "username": "admin_demo",
            "password": "Password123",
            "client_id": "docmind-capacitor",
            "redirect_uri": "docmind://auth/callback",
            "code_challenge": "plain-verifier-123",
            "code_challenge_method": "plain",
            "scope": "openid profile email offline_access",
            "state": "state-1",
        },
    )

    assert authorize_response.status_code == 200
    assert authorize_response.json()["code"] == "auth-code-1234567890"

    token_response = await api_client.post(
        "/api/v1/auth/mobile/token",
        json={
            "grant_type": "authorization_code",
            "client_id": "docmind-capacitor",
            "code": "auth-code-1234567890",
            "redirect_uri": "docmind://auth/callback",
            "code_verifier": "plain-verifier-1234567890",
        },
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    assert token_payload["access_token"] == "access-1"
    assert token_payload["id_token"] == "id-token-1"


@pytest.mark.asyncio
async def test_mobile_userinfo_route_returns_profile(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_userinfo(self, user_id: str):
        assert user_id == "user-1"
        return {
            "sub": "user-1",
            "username": "admin_demo",
            "email": "admin@example.com",
            "email_verified": True,
            "tenant_id": "tenant-1",
            "role": "ADMIN",
            "department": "operations",
        }

    monkeypatch.setattr(MobileOAuthService, "userinfo", fake_userinfo)

    response = await api_client.get("/api/v1/auth/mobile/userinfo")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sub"] == "user-1"
    assert payload["tenant_id"] == "tenant-1"


@pytest.mark.asyncio
async def test_admin_mobile_auth_status_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    def fake_status(self, issuer=None):
        return {
            "enabled": True,
            "ready": True,
            "issues": [],
            "clients": ["docmind-capacitor", "docmind-miniapp"],
            "redirect_uris": ["docmind://auth/callback", "https://servicewechat.com/docmind/callback"],
            "authorization_code_expire_minutes": 5,
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "pkce_methods_supported": ["S256", "plain"],
            "token_endpoint_auth_methods_supported": ["none"],
            "jwt_algorithm": "HS256",
            "client_profiles": [{"client_id": "docmind-miniapp", "recommended_for": "miniapp", "redirect_uris": ["https://servicewechat.com/docmind/callback"]}],
            "miniapp": {
                "ready": True,
                "issues": [],
                "clients": ["docmind-miniapp"],
                "redirect_uris": ["https://servicewechat.com/docmind/callback"],
                "recommended_api_base": "https://testserver/api/v1",
                "recommended_ws_base": "wss://testserver/api/v1/ws/chat",
            },
            "discovery": {"issuer": issuer},
        }

    monkeypatch.setattr(MobileOAuthService, "status", fake_status)

    response = await api_client.get("/api/v1/admin/system/mobile-auth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["ready"] is True
    assert payload["clients"] == ["docmind-capacitor", "docmind-miniapp"]
    assert payload["miniapp"]["ready"] is True


@pytest.mark.asyncio
async def test_admin_push_notification_status_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db
    from app.api.v1 import admin as admin_module
    from app.services.push_notification_service import PushNotificationService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(admin_module, "get_redis", lambda: fake_redis)

    async def fake_health(self, tenant_id: str):
        return {
            "enabled": True,
            "provider": "fcm",
            "fail_closed": False,
            "auto_deactivate_invalid_tokens": True,
            "ready": True,
            "issues": [],
            "providers": {
                "fcm": {
                    "configured": True,
                    "ready": True,
                    "mode": "v1",
                    "required_env_vars": ["PUSH_FCM_ACCESS_TOKEN + PUSH_FCM_PROJECT_ID"],
                    "missing_env_vars": [],
                }
            },
            "tenant_id": tenant_id,
            "device_summary": {"total": 2, "active": 2, "inactive": 0, "by_platform": {"android": 2}},
            "provider_coverage": {"android": {"device_count": 2, "required_provider": "fcm", "provider_ready": True, "delivery_mode": "direct", "deliverable": True}},
            "delivery_gaps": [],
            "redis_available": True,
        }

    monkeypatch.setattr(PushNotificationService, "get_health_summary", fake_health)

    response = await api_client.get("/api/v1/admin/system/push-notifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["provider"] == "fcm"
    assert payload["device_summary"]["total"] == 2
    assert payload["provider_coverage"]["android"]["deliverable"] is True
    assert payload["providers"]["fcm"]["missing_env_vars"] == []


@pytest.mark.asyncio
async def test_admin_llm_training_summary_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db
    from app.api.v1 import admin as admin_module
    from app.services.llm_training_service import LLMTrainingService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(admin_module, "get_redis", lambda: fake_redis)

    async def fake_summary(self, tenant_id: str, *, limit: int = 100):
        assert tenant_id == "tenant-1"
        assert limit == 100
        return {
            "tenant_id": tenant_id,
            "jobs": {"total": 2, "pending": 0, "running": 1, "failed": 1, "status_counts": {"running": 1, "failed": 1}},
            "models": {"total": 2, "active": 1, "canary": 1, "publish_state_counts": {"published": 1, "publish_ready": 1, "not_ready": 0}},
            "active_model": {"model_id": "model-active"},
            "previous_active_model": {"model_id": "model-prev"},
            "can_rollback": True,
            "auto_activate_enabled": True,
            "publish_enabled": True,
            "deploy_verify_enabled": True,
            "deploy_fail_rollback": True,
        }

    monkeypatch.setattr(LLMTrainingService, "summarize_rollout", fake_summary)

    response = await api_client.get("/api/v1/admin/llm/training/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["jobs"]["running"] == 1
    assert payload["models"]["active"] == 1
    assert payload["can_rollback"] is True


@pytest.mark.asyncio
async def test_admin_llm_deployment_summary_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db
    from app.services.llm_training_service import LLMTrainingService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_summary(self, tenant_id: str, *, limit: int = 20):
        assert tenant_id == "tenant-1"
        assert limit == 20
        return {
            "tenant_id": tenant_id,
            "active_model": {"model_id": "model-1"},
            "previous_active_model": {"model_id": "model-prev"},
            "latest_job": {"id": "job-1"},
            "latest_model": {"id": "model-1"},
            "publish_counts": {"published": 1, "publish_ready": 0, "failed": 0, "unknown": 0},
            "verify_counts": {"verified": 1, "failed": 0, "unknown": 0},
            "can_rollback": True,
            "recent_failures": [],
            "auto_activate_enabled": True,
            "publish_enabled": True,
            "deploy_verify_enabled": True,
            "deploy_fail_rollback": True,
        }

    monkeypatch.setattr(LLMTrainingService, "summarize_deployment", fake_summary)

    response = await api_client.get("/api/v1/admin/llm/deployment/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["publish_counts"]["published"] == 1
    assert payload["verify_counts"]["verified"] == 1
    assert payload["can_rollback"] is True


@pytest.mark.asyncio
async def test_admin_llm_publish_model_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db
    from app.services.llm_training_service import LLMTrainingService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_publish(self, *, tenant_id: str, model_id: str):
        assert tenant_id == "tenant-1"
        assert model_id == "model-1"
        return {
            "ok": True,
            "publish_ready": True,
            "published": True,
            "reason": "published",
            "serving_model_name": "tenant-model-1",
        }

    async def fake_activate(self, *, tenant_id: str, model_id: str, actor_id: str | None = None):
        return SimpleNamespace(
            id="model-1",
            tenant_id=tenant_id,
            training_job_id="job-1",
            model_name="tenant-model-1",
            provider="ollama",
            serving_base_url="http://ollama:11434/v1",
            serving_model_name="tenant-model-1",
            base_model="llama3.1:8b",
            artifact_dir="/tmp/artifact",
            source_export_dir="/tmp/export",
            source_dataset_name="swu_public_docs",
            status="active",
            is_active=True,
            canary_percent=0,
            metrics_json="{}",
            notes=None,
            created_by=actor_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            activated_at=datetime.now(timezone.utc),
        )

    async def fake_verify(self, *, tenant_id: str, model_id: str):
        return {"ok": True, "reason": "verified", "url": "http://ollama:11434/health"}

    monkeypatch.setattr(LLMTrainingService, "publish_model_artifact", fake_publish)
    monkeypatch.setattr(LLMTrainingService, "activate_model", fake_activate)
    monkeypatch.setattr(LLMTrainingService, "verify_model_serving", fake_verify)

    response = await api_client.post("/api/v1/admin/llm/models/model-1/publish?activate=true&verify=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["publish_result"]["published"] is True
    assert payload["verify_result"]["ok"] is True
    assert payload["activated_model"]["status"] == "active"


@pytest.mark.asyncio
async def test_admin_public_corpus_latest_compat_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )

    async def override_current_user():
        return current_user

    from app.services.public_corpus_service import PublicCorpusService

    app.dependency_overrides[get_current_user] = override_current_user

    def fake_latest(self, reports_dir, tenant_id="public_cold_start"):
        assert tenant_id == "public_cold_start"
        return {
            "exists": True,
            "tenant_id": tenant_id,
            "export_dir": "/workspace/reports/domain_tuning/public_cold_start/swu_public_docs_latest",
            "manifest_path": "/workspace/reports/domain_tuning/public_cold_start/swu_public_docs_latest/manifest.json",
        }

    monkeypatch.setattr(PublicCorpusService, "latest_export_summary", fake_latest)

    response = await api_client.get("/api/v1/admin/public-corpus/latest?dataset_name=swu_public_docs&tenant_id=public_cold_start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert payload["dataset_name"] == "swu_public_docs"
    assert payload["tenant_id"] == "public_cold_start"
    assert payload["requested_by"] == "user-1"


@pytest.mark.asyncio
async def test_admin_security_summary_route(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    from app.dependencies import get_db
    from app.api.v1 import admin as admin_module
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(admin_module, "get_redis", lambda: fake_redis)

    async def fake_summary(self, tenant_id: str, **kwargs):
        assert tenant_id == "tenant-1"
        return {
            "total": 3,
            "source": "redis",
            "severity_counts": {"high": 2, "medium": 1},
            "action_counts": {"runtime_tool_decision": 2, "runtime_maintenance_alert": 1},
            "result_counts": {"allow": 1, "deny": 1, "warning": 1},
            "top_actions": [{"action": "runtime_tool_decision", "count": 2}],
            "top_severities": [{"severity": "high", "count": 2}],
            "top_results": [{"result": "warning", "count": 1}],
            "trend_by_hour": [{"hour": "2026-05-01T10:00:00+00:00", "ok": 0, "warning": 1, "blocked": 0, "error": 0, "other": 2}],
        }

    monkeypatch.setattr(SecurityAuditService, "summarize_events", fake_summary)

    response = await api_client.get("/api/v1/admin/security/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["severity_counts"]["high"] == 2
    assert payload["action_counts"]["runtime_tool_decision"] == 2


@pytest.mark.asyncio
async def test_chat_message_route_audits_guard_decisions(api_client: AsyncClient, monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()
    audit_events: list[dict] = []

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    class DummyRuntime:
        def __init__(self, _redis):
            pass

        async def run(self, _request, **_kwargs):
            yield {"status": "done", "answer": "请联系 13800138000", "citations": [], "agent_used": "runtime"}

    class DummyMasker:
        def mask(self, text):
            return text, {}

        def restore(self, text, mapping):
            return text

    class DummyCache:
        def __init__(self, _redis):
            pass

        async def get(self, *_args, **_kwargs):
            return None

        async def put(self, *_args, **_kwargs):
            return True

    class DummyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    async def fake_input_check(self, _text: str):
        return {
            "safe": True,
            "blocked": False,
            "reason": "sidecar timeout",
            "severity": "low",
            "issues": [],
            "mode": "degraded",
            "decision_source": "guardrails_sidecar",
            "degraded": True,
        }

    async def fake_output_check(self, _text: str, context=None):
        return {
            "safe": False,
            "blocked": True,
            "reason": "输出内容命中本地敏感信息规则。",
            "severity": "high",
            "issues": ["Possible phone number in output"],
            "mode": "local_rule",
            "decision_source": "local_heuristic",
            "degraded": False,
        }

    async def fake_log_event(self, tenant_id, event_type, severity, message, **kwargs):
        audit_events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "severity": severity,
                "message": message,
                **kwargs,
            }
        )

    from app.dependencies import get_db
    from app.api.v1 import chat as chat_module
    from app.api.middleware import rate_limit as rate_limit_module
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(chat_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.agent.runtime.AgentRuntime", DummyRuntime)
    monkeypatch.setattr("app.retrieval.semantic_cache.SemanticCache", DummyCache)
    monkeypatch.setattr("app.security.pii_masker.PIIMasker", DummyMasker)
    monkeypatch.setattr("app.security.input_guard.InputGuard.check", fake_input_check)
    monkeypatch.setattr("app.security.output_guard.OutputGuard.check", fake_output_check)
    monkeypatch.setattr(SecurityAuditService, "log_event", fake_log_event)
    async def fake_execute(self, *_args, **_kwargs):
        return DummyResult()

    monkeypatch.setattr(DummyDB, "execute", fake_execute)

    response = await api_client.post(
        "/api/v1/chat/message",
        json={"message": "请总结制度并附联系方式", "search_type": "hybrid"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_used"] == "output_guard"
    assert payload["answer"] == "输出内容命中安全规则，系统已拦截。"
    assert [item["event_type"] for item in audit_events] == ["input_guard_decision", "output_guard_decision"]
    assert audit_events[0]["result"] == "warning"
    assert audit_events[1]["result"] == "blocked"


@pytest.mark.asyncio
async def test_ws_handle_chat_message_audits_guard_decisions(monkeypatch):
    current_user = SimpleNamespace(
        id="user-1",
        username="admin_demo",
        email="admin@example.com",
        role="ADMIN",
        department="operations",
        tenant_id="tenant-1",
        level=9,
        email_verified=True,
        created_at=datetime.now(timezone.utc),
    )
    fake_redis = FakeRedis()
    audit_events: list[dict] = []

    class FakeWebSocket:
        def __init__(self):
            self.sent: list[dict] = []

        async def send_json(self, payload):
            self.sent.append(payload)

    class DummyWsDB(DummyDB):
        async def scalar(self, *_args, **_kwargs):
            return None

        async def execute(self, *_args, **_kwargs):
            class DummyResult:
                def scalars(self_inner):
                    return self_inner

                def all(self_inner):
                    return []

            return DummyResult()

    class DummyRuntime:
        def __init__(self, _redis):
            pass

        async def run(self, _request, **_kwargs):
            yield {"status": "thinking", "msg": "正在分析"}
            yield {"status": "done", "answer": "制度要点总结", "citations": [], "trace_id": "trace-ws-1"}

    class DummyMasker:
        def mask(self, text):
            return text, {}

        def restore(self, text, mapping):
            return text

    class DummyCache:
        def __init__(self, _redis):
            pass

        async def get(self, *_args, **_kwargs):
            return None

        async def put(self, *_args, **_kwargs):
            return True

    async def fake_input_check(self, _text: str):
        return {
            "safe": True,
            "blocked": False,
            "reason": "sidecar timeout",
            "severity": "low",
            "issues": [],
            "mode": "degraded",
            "decision_source": "guardrails_sidecar",
            "degraded": True,
        }

    async def fake_output_check(self, _text: str, context=None):
        return {
            "safe": True,
            "blocked": False,
            "reason": "",
            "severity": "low",
            "issues": [],
            "mode": "sidecar",
            "decision_source": "guardrails_sidecar",
            "degraded": False,
        }

    async def fake_log_event(self, tenant_id, event_type, severity, message, **kwargs):
        audit_events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "severity": severity,
                "message": message,
                **kwargs,
            }
        )

    from app.api.v1 import ws_chat as ws_chat_module
    from app.services.security_audit_service import SecurityAuditService

    monkeypatch.setattr(ws_chat_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.agent.runtime.AgentRuntime", DummyRuntime)
    monkeypatch.setattr("app.retrieval.semantic_cache.SemanticCache", DummyCache)
    monkeypatch.setattr("app.security.pii_masker.PIIMasker", DummyMasker)
    monkeypatch.setattr("app.security.input_guard.InputGuard.check", fake_input_check)
    monkeypatch.setattr("app.security.output_guard.OutputGuard.check", fake_output_check)
    monkeypatch.setattr(SecurityAuditService, "log_event", fake_log_event)

    websocket = FakeWebSocket()
    db = DummyWsDB()

    await ws_chat_module._handle_chat_message(
        websocket=websocket,
        db=db,
        current_user=current_user,
        content="请总结制度",
        thread_id=None,
        search_type="hybrid",
    )

    assert [item["event_type"] for item in audit_events] == ["input_guard_decision", "output_guard_decision"]
    assert audit_events[0]["result"] == "warning"
    assert audit_events[1]["result"] == "ok"
    assert any(item["type"] == "done" for item in websocket.sent)
