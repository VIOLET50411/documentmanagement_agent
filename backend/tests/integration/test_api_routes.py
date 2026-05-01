from __future__ import annotations

import json
import sys
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

    def add(self, _item):
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
            "clients": ["docmind-capacitor"],
            "redirect_uris": ["docmind://auth/callback"],
            "authorization_code_expire_minutes": 5,
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "pkce_methods_supported": ["S256", "plain"],
            "token_endpoint_auth_methods_supported": ["none"],
            "jwt_algorithm": "HS256",
            "discovery": {"issuer": issuer},
        }

    monkeypatch.setattr(MobileOAuthService, "status", fake_status)

    response = await api_client.get("/api/v1/admin/system/mobile-auth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["ready"] is True
    assert payload["clients"] == ["docmind-capacitor"]


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
            "providers": {"fcm": {"configured": True, "ready": True, "mode": "v1"}},
            "tenant_id": tenant_id,
            "device_summary": {"total": 2, "active": 2, "inactive": 0, "by_platform": {"android": 2}},
            "redis_available": True,
        }

    monkeypatch.setattr(PushNotificationService, "get_health_summary", fake_health)

    response = await api_client.get("/api/v1/admin/system/push-notifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["provider"] == "fcm"
    assert payload["device_summary"]["total"] == 2
