from __future__ import annotations

import json
import sys
import tempfile
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
        self.deleted_items: list[object] = []

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

    async def delete(self, item):
        self.deleted_items.append(item)
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


def test_format_history_message_appends_citation_titles():
    from app.api.v1.chat import _format_history_message
    from app.models.db.session import ChatMessage

    item = ChatMessage(
        session_id="session-1",
        role="assistant",
        content="这是回答正文。",
    )
    item.citations_json = json.dumps(
        [
            {"doc_title": "差旅报销制度"},
            {"doc_title": "财务审批规范"},
        ],
        ensure_ascii=False,
    )

    payload = _format_history_message(item)

    assert "[参考文档: 差旅报销制度、财务审批规范]" in payload["content"]
    assert payload["role"] == "assistant"


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
async def test_chat_sessions_route_returns_recent_threads(api_client: AsyncClient):
    from app.models.db.session import ChatSession
    from app.dependencies import get_db

    current_user = SimpleNamespace(id="user-1", username="admin_demo", role="ADMIN", tenant_id="tenant-1")
    session_a = ChatSession(id="thread-1", user_id="user-1", tenant_id="tenant-1", title="差旅报销怎么走")
    session_a.created_at = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
    session_a.updated_at = datetime(2026, 5, 10, 10, 5, tzinfo=timezone.utc)
    session_b = ChatSession(id="thread-2", user_id="user-1", tenant_id="tenant-1", title="预算报表怎么查")
    session_b.created_at = datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc)
    session_b.updated_at = datetime(2026, 5, 11, 9, 30, tzinfo=timezone.utc)
    execute_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [session_b, session_a]))

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB(execute_value=execute_value)

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    response = await api_client.get("/api/v1/chat/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["thread-2", "thread-1"]
    assert payload["items"][0]["title"] == "预算报表怎么查"


@pytest.mark.asyncio
async def test_delete_chat_session_route_removes_session_and_messages(api_client: AsyncClient):
    from app.models.db.session import ChatMessage, ChatSession
    from app.dependencies import get_db

    current_user = SimpleNamespace(id="user-1", username="admin_demo", role="ADMIN", tenant_id="tenant-1")
    session = ChatSession(id="thread-1", user_id="user-1", tenant_id="tenant-1", title="待删除会话")
    message_a = ChatMessage(id="msg-1", session_id="thread-1", role="user", content="问题")
    message_b = ChatMessage(id="msg-2", session_id="thread-1", role="assistant", content="回答")
    execute_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [message_a, message_b]))
    dummy_db = DummyDB(scalar_value=session, execute_value=execute_value)

    async def override_current_user():
        return current_user

    async def override_db():
        yield dummy_db

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    response = await api_client.delete("/api/v1/chat/sessions/thread-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["thread_id"] == "thread-1"
    assert dummy_db.deleted_items == [message_a, message_b, session]


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
    audit_events: list[dict] = []

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
            assert _request.query == "[MASKED]"
            yield {
                "status": "reading",
                "trace_id": trace_id,
                "event_id": "evt-r1",
                "sequence_num": 1,
                "source": "agent_runtime_v2_resume",
                "msg": "宸蹭粠妫€鏌ョ偣鎭㈠",
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

    class DummyMasker:
        def mask(self, text):
            assert text == "鎭㈠浼氳瘽"
            return "[MASKED]", {"[PHONE_1]": "13800138000"}

        def restore(self, text, mapping):
            assert mapping == {"[PHONE_1]": "13800138000"}
            return f"{text} 13800138000"

    async def fake_input_check(self, _text: str):
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
    monkeypatch.setattr("app.security.pii_masker.PIIMasker", DummyMasker)
    monkeypatch.setattr("app.security.input_guard.InputGuard.check", fake_input_check)
    monkeypatch.setattr("app.security.output_guard.OutputGuard.check", fake_output_check)
    monkeypatch.setattr(SecurityAuditService, "log_event", fake_log_event)

    async with api_client.stream(
        "POST",
        f"/api/v1/chat/stream?resume_trace_id={trace_id}&last_sequence=0",
        json={"message": "鎭㈠浼氳瘽", "thread_id": "thread-1", "search_type": "hybrid"},
    ) as response:
        assert response.status_code == 200
        body = ""
        async for chunk in response.aiter_text():
            body += chunk

    assert '"status": "reading"' in body
    assert '"输出内容命中安全规则，系统已拦截。"' in body
    assert [item["event_type"] for item in audit_events] == ["input_guard_decision", "output_guard_decision"]
    assert audit_events[0]["target"] == "chat.resume.query"
    assert audit_events[1]["target"] == "chat.resume.answer"


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
async def test_documents_upload_session_route_accepts_json_payload(api_client: AsyncClient, monkeypatch):
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
    from app.api.v1 import documents as documents_module
    from app.api.middleware import rate_limit as rate_limit_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(documents_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: fake_redis)

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(documents_module, "UPLOAD_TMP_ROOT", Path(tmpdir))
        response = await api_client.post(
            "/api/v1/documents/upload/session",
            json={
                "file_name": "big.csv",
                "content_type": "text/csv",
                "file_size": 9 * 1024 * 1024,
                "total_parts": 2,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_name"] == "big.csv"
    assert payload["total_parts"] == 2
    assert payload["department"] == "operations"
    assert payload["tenant_id"] == "tenant-1"


@pytest.mark.asyncio
async def test_documents_chunk_upload_flow_merges_and_enqueues(api_client: AsyncClient, monkeypatch):
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
    merged_payload = {}

    async def override_current_user():
        return current_user

    async def override_db():
        yield DummyDB()

    async def fake_store_local_file_and_enqueue(self, **kwargs):
        merged_payload["path"] = kwargs["local_path"]
        merged_payload["bytes"] = Path(kwargs["local_path"]).read_bytes()
        return {
            "id": kwargs["doc_id"],
            "title": kwargs["file_name"],
            "file_name": kwargs["file_name"],
            "file_type": kwargs["content_type"],
            "status": "queued",
            "task_id": "task-chunk-1",
            "percentage": 0,
            "file_size": len(merged_payload["bytes"]),
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
    monkeypatch.setattr("app.services.document_service.DocumentService.store_local_file_and_enqueue", fake_store_local_file_and_enqueue)
    monkeypatch.setattr("app.security.file_scanner.FileScanner.scan_bytes", lambda self, content: {"safe": True, "reason": "ok", "engine": "test"})
    monkeypatch.setattr(documents_module, "get_minio_client", lambda: object())
    monkeypatch.setattr(documents_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rate_limit_module, "get_redis", lambda: fake_redis)

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(documents_module, "UPLOAD_TMP_ROOT", Path(tmpdir))
        session_response = await api_client.post(
            "/api/v1/documents/upload/session",
            json={
                "file_name": "big.csv",
                "content_type": "text/csv",
                "file_size": 9 * 1024 * 1024,
                "total_parts": 2,
            },
        )
        assert session_response.status_code == 200
        upload_id = session_response.json()["upload_id"]

        part1 = await api_client.post(
            "/api/v1/documents/upload/chunk",
            files={"chunk": ("chunk-1", b"hello ", "application/octet-stream")},
            data={"upload_id": upload_id, "part_number": "1", "total_parts": "2"},
        )
        assert part1.status_code == 200
        assert part1.json()["percentage"] == 50

        part2 = await api_client.post(
            "/api/v1/documents/upload/chunk",
            files={"chunk": ("chunk-2", b"world", "application/octet-stream")},
            data={"upload_id": upload_id, "part_number": "2", "total_parts": "2"},
        )
        assert part2.status_code == 200
        assert part2.json()["percentage"] == 100

        complete = await api_client.post(
            "/api/v1/documents/upload/complete",
            params={"upload_id": upload_id},
        )

    assert complete.status_code == 202
    payload = complete.json()
    assert payload["status"] == "queued"
    assert merged_payload["bytes"] == b"hello world"
    assert fake_redis.values.get(f"upload:session:{upload_id}") is None


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
                    "next_step": "运行凭据已到位，可直接联调真实推送。",
                }
            },
            "tenant_id": tenant_id,
            "device_summary": {"total": 2, "active": 2, "inactive": 0, "by_platform": {"android": 2}},
            "provider_coverage": {"android": {"device_count": 2, "required_provider": "fcm", "provider_ready": True, "delivery_mode": "direct", "deliverable": True}},
            "delivery_gaps": [],
            "configuration_sources": {
                "fcm": {"source": "access_token", "configured": True, "detail": "example-firebase-project"},
                "wechat": {"source": "none", "configured": False, "detail": None},
                "webhook": {"source": "none", "configured": False, "detail": None},
            },
            "setup_guides": {
                "fcm": {
                    "configured": True,
                    "ready": True,
                    "required_env_vars": ["PUSH_FCM_ACCESS_TOKEN + PUSH_FCM_PROJECT_ID"],
                    "missing_env_vars": [],
                    "env_examples": ["PUSH_FCM_ACCESS_TOKEN=<token>"],
                    "secret_targets": [],
                    "docker_mount_dir": "/run/secrets/docmind",
                    "next_step": "运行凭据已到位，可直接联调真实推送。",
                },
                "wechat": {
                    "configured": False,
                    "ready": False,
                    "required_env_vars": ["PUSH_WECHAT_ACCESS_TOKEN or PUSH_WECHAT_APP_ID + PUSH_WECHAT_APP_SECRET", "PUSH_WECHAT_TEMPLATE_ID"],
                    "missing_env_vars": ["PUSH_WECHAT_ACCESS_TOKEN", "PUSH_WECHAT_APP_ID", "PUSH_WECHAT_APP_SECRET", "PUSH_WECHAT_TEMPLATE_ID"],
                    "env_examples": ["PUSH_WECHAT_TEMPLATE_ID=<subscribe-template-id>"],
                    "secret_targets": [],
                    "docker_mount_dir": "/run/secrets/docmind",
                    "next_step": "补齐小程序 access token 或 appid/appsecret，以及订阅消息模板 ID 后即可联调微信通知。",
                },
                "webhook": {
                    "configured": False,
                    "ready": False,
                    "required_env_vars": ["PUSH_NOTIFICATION_WEBHOOK_URL"],
                    "missing_env_vars": ["PUSH_NOTIFICATION_WEBHOOK_URL"],
                    "env_examples": ["PUSH_NOTIFICATION_WEBHOOK_URL=https://push-gateway.example.com/webhook"],
                    "secret_targets": [],
                    "docker_mount_dir": "/run/secrets/docmind",
                    "next_step": "补齐 webhook 地址后即可联调外部推送网关。",
                },
            },
            "readiness_score": 100,
            "action_items": [],
            "provider_diagnostics": {
                "fcm": {
                    "configured": True,
                    "ready": True,
                    "code_ready": True,
                    "missing_env_vars": [],
                    "required_env_vars": ["PUSH_FCM_ACCESS_TOKEN + PUSH_FCM_PROJECT_ID"],
                    "transport": "https",
                    "delivery_mode": "v1",
                    "supports_platforms": ["android"],
                    "next_step": "运行凭据已到位，可直接联调真实推送。",
                    "env_examples": ["PUSH_FCM_ACCESS_TOKEN=<token>"],
                    "secret_targets": [],
                }
            },
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
    assert payload["configuration_sources"]["fcm"]["source"] == "access_token"
    assert payload["readiness_score"] == 100
    assert payload["setup_guides"]["wechat"]["env_examples"] == ["PUSH_WECHAT_TEMPLATE_ID=<subscribe-template-id>"]
    assert payload["provider_diagnostics"]["fcm"]["next_step"] == "运行凭据已到位，可直接联调真实推送。"


@pytest.mark.asyncio
async def test_admin_security_policy_route(api_client: AsyncClient, monkeypatch):
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

    monkeypatch.setattr(
        "app.services.security_policy_service.SecurityPolicyService.evaluate",
        lambda self: {
            "profile": "financial",
            "enforcement_level": "financial_fail_closed",
            "compliant": False,
            "blocking": True,
            "status": "blocked",
            "auto_action": "block_high_risk_operations",
            "failed_controls": [{"id": "guardrails_fail_closed", "message": "missing"}],
            "blocking_controls": [{"id": "guardrails_fail_closed", "severity": "critical"}],
            "warning_controls": [],
            "required_control_ids": ["guardrails_fail_closed"],
            "missing_control_ids": ["guardrails_fail_closed"],
            "control_counts": {"ok": 0, "critical": 1, "high": 0, "medium": 0, "low": 0},
            "recommended_actions": ["开启 Guardrails fail-closed。"],
            "controls": [],
            "clamav_health": {"available": True},
            "guardrails_sidecar": {"configured": True, "fail_closed": False, "alive": True},
            "pii": {"masking_enabled": True, "presidio_enabled": True},
        },
    )

    app.dependency_overrides[get_current_user] = override_current_user

    response = await api_client.get("/api/v1/admin/system/security-policy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "financial"
    assert payload["blocking"] is True
    assert payload["status"] == "blocked"
    assert payload["auto_action"] == "block_high_risk_operations"
    assert payload["missing_control_ids"] == ["guardrails_fail_closed"]
    assert payload["recommended_actions"] == ["开启 Guardrails fail-closed。"]


@pytest.mark.asyncio
async def test_admin_gap_report_route_includes_blocker_summaries(api_client: AsyncClient, monkeypatch):
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
    from app.services.delivery_gap_service import DeliveryGapService
    from app.services.push_notification_service import PushNotificationService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.api.v1.admin.get_redis", lambda: FakeRedis())

    async def fake_build_report(self, tenant_id: str | None = None):
        assert tenant_id == "tenant-1"
        return {
            "target_profile": "financial",
            "tenant_id": "tenant-1",
            "completed": ["runtime_v2_only"],
            "in_progress": [],
            "pending": ["wechat_push_provider_ready"],
            "summary": {
                "completed_count": 1,
                "in_progress_count": 0,
                "pending_count": 1,
                "internal_blocker_count": 0,
                "external_blocker_count": 1,
                "completion_percent": 50.0,
            },
            "blockers": [
                {
                    "id": "wechat_push_provider_ready",
                    "scope": "external",
                    "provider": "wechat",
                    "missing_env_vars": ["PUSH_WECHAT_TEMPLATE_ID"],
                    "next_step": "补齐小程序 access token 或 appid/appsecret，以及订阅消息模板 ID 后即可联调微信通知。",
                },
            ],
            "external_blockers": [
                {"id": "wechat_push_provider_ready", "scope": "external", "provider": "wechat"},
            ],
            "internal_blockers": [],
            "notes": ["当前仅剩外部 provider 凭据待补齐。"],
        }

    async def fake_health(self, *, tenant_id: str):
        assert tenant_id == "tenant-1"
        return {
            "tenant_id": tenant_id,
            "ready": True,
            "providers": {"fcm": {"ready": True}, "wechat": {"ready": False}},
        }

    monkeypatch.setattr(DeliveryGapService, "build_report", fake_build_report)
    monkeypatch.setattr(PushNotificationService, "get_health_summary", fake_health)

    response = await api_client.get("/api/v1/admin/system/gap-report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["external_blocker_count"] == 1
    assert payload["summary"]["completion_percent"] == 50.0
    assert {item["provider"] for item in payload["external_blockers"]} == {"wechat"}
    assert payload["push_runtime_status"]["providers"]["fcm"]["ready"] is True


@pytest.mark.asyncio
async def test_admin_model_approval_route(api_client: AsyncClient, monkeypatch):
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
    from app.api.v1 import admin as admin_module
    from app.services.llm_training_service import LLMTrainingService
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(admin_module, "get_redis", lambda: FakeRedis())

    async def fake_record(self, *, tenant_id: str, model_id: str, approved: bool, actor_id: str | None = None, reason: str | None = None):
        assert tenant_id == "tenant-1"
        assert model_id == "model-1"
        assert approved is True
        assert actor_id == "user-1"
        assert reason == "qa passed"
        return {"required": True, "approved": True, "decision": "approved", "ready": True, "reason": "qa passed"}

    async def fake_get_model(self, tenant_id: str, model_id: str):
        return SimpleNamespace(
            id=model_id,
            tenant_id=tenant_id,
            training_job_id="job-1",
            model_name="tenant-model",
            provider="ollama",
            serving_base_url="http://ollama:11434/v1",
            serving_model_name="tenant-model",
            base_model="llama3.1:8b",
            artifact_dir="/tmp/model",
            source_export_dir="/tmp/export",
            source_dataset_name="dataset",
            status="published",
            is_active=False,
            canary_percent=0,
            metrics_json='{"approval":{"decision":"approved"}}',
            notes="",
            created_by="user-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            activated_at=None,
        )

    async def fake_log(self, tenant_id: str, event_type: str, severity: str, message: str, **kwargs):
        return None

    monkeypatch.setattr(LLMTrainingService, "record_model_approval", fake_record)
    monkeypatch.setattr(LLMTrainingService, "get_model", fake_get_model)
    monkeypatch.setattr(SecurityAuditService, "log_event", fake_log)

    response = await api_client.post("/api/v1/admin/llm/models/model-1/approve?reason=qa%20passed")

    assert response.status_code == 200
    payload = response.json()
    assert payload["approval"]["decision"] == "approved"
    assert payload["item"]["id"] == "model-1"


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
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(admin_module, "get_redis", lambda: fake_redis)

    async def fake_list_models(self, tenant_id: str, limit: int = 100):
        assert tenant_id == "tenant-1"
        assert limit == 100
        return []

    async def fake_reconcile(self, tenant_id: str, models=None):
        assert tenant_id == "tenant-1"
        return False

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

    monkeypatch.setattr(LLMTrainingService, "list_models", fake_list_models)
    monkeypatch.setattr(LLMTrainingService, "reconcile_model_registry_states", fake_reconcile)
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

    async def fake_list_models(self, tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        assert limit == 20
        return []

    async def fake_reconcile(self, tenant_id: str, models=None):
        assert tenant_id == "tenant-1"
        return False

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
            "approval_counts": {"approved": 1, "pending": 0, "rejected": 0, "not_required": 0},
            "can_rollback": True,
            "recent_failures": [],
            "auto_activate_enabled": True,
            "publish_enabled": True,
            "manual_approval_required": True,
            "deploy_verify_enabled": True,
            "deploy_fail_rollback": True,
        }

    monkeypatch.setattr(LLMTrainingService, "list_models", fake_list_models)
    monkeypatch.setattr(LLMTrainingService, "reconcile_model_registry_states", fake_reconcile)
    monkeypatch.setattr(LLMTrainingService, "summarize_deployment", fake_summary)

    response = await api_client.get("/api/v1/admin/llm/deployment/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["publish_counts"]["published"] == 1
    assert payload["verify_counts"]["verified"] == 1
    assert payload["approval_counts"]["approved"] == 1
    assert payload["manual_approval_required"] is True
    assert payload["can_rollback"] is True


@pytest.mark.asyncio
async def test_admin_llm_training_deployment_alias_route(api_client: AsyncClient, monkeypatch):
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

    async def fake_list_models(self, tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        assert limit == 20
        return []

    async def fake_reconcile(self, tenant_id: str, models=None):
        assert tenant_id == "tenant-1"
        return False

    async def fake_summary(self, tenant_id: str, *, limit: int = 20):
        assert tenant_id == "tenant-1"
        assert limit == 20
        return {
            "tenant_id": tenant_id,
            "publish_counts": {"published": 2, "publish_ready": 1, "failed": 0, "unknown": 0},
            "verify_counts": {"verified": 2, "failed": 0, "unknown": 0},
            "approval_counts": {"approved": 2, "pending": 0, "rejected": 0, "not_required": 0},
            "can_rollback": True,
            "manual_approval_required": False,
        }

    monkeypatch.setattr(LLMTrainingService, "list_models", fake_list_models)
    monkeypatch.setattr(LLMTrainingService, "reconcile_model_registry_states", fake_reconcile)
    monkeypatch.setattr(LLMTrainingService, "summarize_deployment", fake_summary)

    response = await api_client.get("/api/v1/admin/llm/training/deployment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["publish_counts"]["published"] == 2
    assert payload["verify_counts"]["verified"] == 2
    assert payload["approval_counts"]["approved"] == 2
    assert payload["manual_approval_required"] is False
    assert payload["can_rollback"] is True


@pytest.mark.asyncio
async def test_admin_llm_retire_nonrecoverable_route(api_client: AsyncClient, monkeypatch):
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
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(admin_module, "get_redis", lambda: fake_redis)

    async def fake_list_models(self, tenant_id: str, limit: int = 100):
        assert tenant_id == "tenant-1"
        assert limit == 20
        return []

    async def fake_reconcile(self, tenant_id: str, models=None):
        assert tenant_id == "tenant-1"
        return False

    async def fake_retire(self, *, tenant_id: str, limit: int = 20, dry_run: bool = True, actor_id: str | None = None):
        assert tenant_id == "tenant-1"
        assert limit == 4
        assert dry_run is False
        assert actor_id == "user-1"
        return {
            "tenant_id": tenant_id,
            "dry_run": dry_run,
            "limit": limit,
            "changed_count": 2,
            "retired_count": 2,
            "skipped_count": 1,
            "retired": [{"model_id": "model-1"}, {"model_id": "model-2"}],
            "skipped": [{"model_id": "model-3", "reason": "recoverable_failure"}],
        }

    monkeypatch.setattr(LLMTrainingService, "list_models", fake_list_models)
    monkeypatch.setattr(LLMTrainingService, "reconcile_model_registry_states", fake_reconcile)
    monkeypatch.setattr(LLMTrainingService, "retire_nonrecoverable_models", fake_retire)
    async def fake_log_event(self, *args, **kwargs):
        return None

    monkeypatch.setattr(SecurityAuditService, "log_event", fake_log_event)

    response = await api_client.post("/api/v1/admin/llm/models/retire-nonrecoverable?limit=4&dry_run=false")

    assert response.status_code == 200
    payload = response.json()
    assert payload["retired_count"] == 2
    assert payload["changed_count"] == 2
    assert payload["dry_run"] is False


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
async def test_runtime_tool_decisions_merged_deduplicates_dual_written_rows(api_client: AsyncClient, monkeypatch):
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
    from app.agent.runtime.permission_gate import PermissionGate
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_list_decisions(self, tenant_id: str, limit: int = 100, offset: int = 0):
        assert tenant_id == "tenant-1"
        return [
            {
                "decision": "deny",
                "reason": "tool_disabled",
                "source": "tool_spec",
                "tool_name": "web_search",
                "user_id": "user-1",
                "tenant_id": tenant_id,
                "trace_id": "trace-1",
                "created_at": "2026-05-03T10:11:22",
            }
        ]

    async def fake_list_events(self, tenant_id: str, **kwargs):
        assert tenant_id == "tenant-1"
        return {
            "events": [
                {
                    "result": "deny",
                    "message": "tool_disabled",
                    "tenant_id": tenant_id,
                    "user_id": "user-1",
                    "trace_id": "trace-1",
                    "timestamp": "2026-05-03T10:11:45",
                    "metadata": {"reason": "tool_disabled", "tool_name": "web_search", "source": "tool_spec"},
                },
                {
                    "result": "allow",
                    "message": "policy_pass",
                    "tenant_id": tenant_id,
                    "user_id": "user-1",
                    "trace_id": "trace-2",
                    "timestamp": "2026-05-03T10:12:10",
                    "metadata": {"reason": "policy_pass", "tool_name": "doc_lookup", "source": "rbac"},
                },
            ],
            "total": 2,
            "source": "postgres",
        }

    monkeypatch.setattr(PermissionGate, "list_decisions", fake_list_decisions)
    monkeypatch.setattr(SecurityAuditService, "list_events", fake_list_events)

    response = await api_client.get("/api/v1/admin/runtime/tool-decisions?source=merged&limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["items"][0]["tool_name"] in {"web_search", "doc_lookup"}
    deny_items = [item for item in payload["items"] if item["tool_name"] == "web_search"]
    assert len(deny_items) == 1
    assert deny_items[0]["channel"] == "merged"


@pytest.mark.asyncio
async def test_runtime_tool_decisions_summary_deduplicates_dual_written_rows(api_client: AsyncClient, monkeypatch):
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
    from app.agent.runtime.permission_gate import PermissionGate
    from app.services.security_audit_service import SecurityAuditService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_list_decisions(self, tenant_id: str, limit: int = 1000, offset: int = 0):
        return [
            {
                "decision": "deny",
                "reason": "tool_disabled",
                "source": "tool_spec",
                "tool_name": "web_search",
                "user_id": "user-1",
                "tenant_id": tenant_id,
                "trace_id": "trace-1",
                "created_at": "2026-05-03T10:11:22",
            }
        ]

    async def fake_list_events(self, tenant_id: str, **kwargs):
        return {
            "events": [
                {
                    "result": "deny",
                    "message": "tool_disabled",
                    "tenant_id": tenant_id,
                    "user_id": "user-1",
                    "trace_id": "trace-1",
                    "timestamp": "2026-05-03T10:11:45",
                    "metadata": {"reason": "tool_disabled", "tool_name": "web_search", "source": "tool_spec"},
                },
                {
                    "result": "allow",
                    "message": "policy_pass",
                    "tenant_id": tenant_id,
                    "user_id": "user-1",
                    "trace_id": "trace-2",
                    "timestamp": "2026-05-03T10:12:10",
                    "metadata": {"reason": "policy_pass", "tool_name": "doc_lookup", "source": "rbac"},
                },
            ],
            "total": 2,
            "source": "postgres",
        }

    monkeypatch.setattr(PermissionGate, "list_decisions", fake_list_decisions)
    monkeypatch.setattr(SecurityAuditService, "list_events", fake_list_events)

    response = await api_client.get("/api/v1/admin/runtime/tool-decisions/summary?since_hours=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["decision_counts"]["deny"] == 1
    assert payload["decision_counts"]["allow"] == 1
    assert any(row["tool_name"] == "web_search" and row["deny"] == 1 for row in payload["matrix_by_tool"])
    assert any(row["reason"] == "tool_disabled" and row["deny"] == 1 for row in payload["matrix_by_reason"])


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
            yield {"status": "thinking", "msg": "姝ｅ湪鍒嗘瀽"}
            yield {"status": "done", "answer": "鍒跺害瑕佺偣鎬荤粨", "citations": [], "trace_id": "trace-ws-1"}

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


@pytest.mark.asyncio
async def test_ws_handle_chat_message_hides_runtime_exception_details(monkeypatch):
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
            raise RuntimeError("secret backend stack")
            yield  # pragma: no cover

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
            "reason": "",
            "severity": "low",
            "issues": [],
            "mode": "sidecar",
            "decision_source": "guardrails_sidecar",
            "degraded": False,
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

    assert websocket.sent[-1] == {"type": "error", "msg": "运行时处理失败，请稍后重试。"}
    assert audit_events[-1]["event_type"] == "ws_runtime_exception"
    assert audit_events[-1]["metadata"]["detail"] == "secret backend stack"


@pytest.mark.asyncio
async def test_admin_evaluation_history_route(api_client: AsyncClient, monkeypatch):
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
    from app.services.evaluation_service import EvaluationService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_history(self, tenant_id: str, *, limit: int = 30):
        assert tenant_id == "tenant-1"
        assert limit == 5
        return {
            "items": [
                {
                    "generated_at": "2026-05-03T10:00:00+00:00",
                    "dataset_size": 5,
                    "gate": {"passed": True, "failures": []},
                    "metrics": {"faithfulness": 0.95},
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(EvaluationService, "history", fake_history)

    response = await api_client.get("/api/v1/admin/evaluation/history?limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["gate"]["passed"] is True


@pytest.mark.asyncio
async def test_admin_evaluation_gate_summary_route(api_client: AsyncClient, monkeypatch):
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
    from app.services.evaluation_service import EvaluationService

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_summary(self, tenant_id: str, *, limit: int = 30):
        assert tenant_id == "tenant-1"
        assert limit == 7
        return {
            "tenant_id": tenant_id,
            "count": 2,
            "pass_rate": 0.5,
            "real_mode_rate": 0.5,
            "latest_generated_at": "2026-05-03T11:00:00+00:00",
            "failure_reasons": {"faithfulness": 1, "real_mode": 1},
            "metric_averages": {"faithfulness": 0.775},
            "trend": [],
        }

    monkeypatch.setattr(EvaluationService, "summarize_history", fake_summary)

    response = await api_client.get("/api/v1/admin/evaluation/gate-summary?limit=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["pass_rate"] == 0.5
    assert payload["failure_reasons"]["faithfulness"] == 1


@pytest.mark.asyncio
async def test_admin_run_evaluation_async_route(api_client: AsyncClient, monkeypatch):
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

    class DummyTask:
        id = "eval-task-1"

    from app.dependencies import get_db
    from app.api.v1 import admin as admin_module

    async def override_db():
        yield DummyDB()

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    seeded: list[dict] = []

    async def fake_seed(task_id: str, *, tenant_id: str, task_type: str, description: str, stage: str = "queued"):
        seeded.append({
            "task_id": task_id,
            "tenant_id": tenant_id,
            "task_type": task_type,
            "description": description,
            "stage": stage,
        })

    class FakeCeleryTask:
        def apply_async(self, args=(), queue=None):
            assert args == ("tenant-1", 5, "user-1")
            assert queue is not None
            return DummyTask()

    from app.api.v1.admin import evaluation as eval_module
    monkeypatch.setattr(eval_module, "_seed_runtime_task", fake_seed)
    monkeypatch.setattr("app.maintenance.tasks.run_evaluation_job", FakeCeleryTask())

    response = await api_client.post("/api/v1/admin/evaluation/run-async?sample_limit=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "eval-task-1"
    assert payload["sample_limit"] == 5
    assert seeded[0]["task_type"] == "evaluation"


@pytest.mark.asyncio
async def test_admin_get_evaluation_task_route(api_client: AsyncClient, monkeypatch):
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
    from app.api.v1 import admin as admin_module

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_db] = override_db

    async def fake_get_runtime_task_payload(task_id: str, *, tenant_id: str, expected_type: str):
        assert task_id == "eval-task-2"
        assert tenant_id == "tenant-1"
        assert expected_type == "evaluation"
        return {"exists": True, "item": {"task_id": task_id, "status": "completed"}, "result": {"ok": True}}

    from app.api.v1.admin import evaluation as eval_module
    monkeypatch.setattr(eval_module, "_get_runtime_task_payload", fake_get_runtime_task_payload)

    response = await api_client.get("/api/v1/admin/evaluation/tasks/eval-task-2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert payload["item"]["status"] == "completed"
