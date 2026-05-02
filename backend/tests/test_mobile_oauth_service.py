from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.mobile_oauth_service import MobileOAuthService


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, responses: list[object]):
        self.responses = list(responses)
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None

    async def execute(self, _query):
        value = self.responses.pop(0) if self.responses else None
        return FakeResult(value)


@pytest.mark.asyncio
async def test_mobile_authorize_creates_code(monkeypatch):
    user = SimpleNamespace(
        id="user-1",
        tenant_id="tenant-1",
        username="demo",
        email="demo@example.com",
        email_verified=True,
        role="ADMIN",
    )
    db = FakeDB([])
    service = MobileOAuthService(db)

    async def fake_authenticate(_username: str, _password: str):
        return user

    monkeypatch.setattr(service.auth_service, "authenticate", fake_authenticate)

    record = await service.authorize(
        username="demo",
        password="Password123",
        client_id="docmind-capacitor",
        redirect_uri="docmind://auth/callback",
        code_challenge="challenge-value-123456",
        code_challenge_method="plain",
        scope="openid profile",
    )

    assert record.user_id == "user-1"
    assert db.added


@pytest.mark.asyncio
async def test_mobile_exchange_code_returns_id_token(monkeypatch):
    user = SimpleNamespace(
        id="user-1",
        tenant_id="tenant-1",
        username="demo",
        email="demo@example.com",
        email_verified=True,
        role="ADMIN",
        is_active=True,
    )
    record = SimpleNamespace(
        code="code-1",
        client_id="docmind-capacitor",
        redirect_uri="docmind://auth/callback",
        code_challenge="verifier-1234567890",
        code_challenge_method="plain",
        consumed=False,
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(tzinfo=None, microsecond=0)
        + __import__("datetime").timedelta(minutes=5),
        user_id="user-1",
        tenant_id="tenant-1",
        scope="openid profile",
    )
    db = FakeDB([record, user])
    service = MobileOAuthService(db)

    monkeypatch.setattr(
        service.auth_service,
        "create_tokens",
        lambda _user: {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_type": "bearer",
            "expires_in": 1800,
        },
    )

    tokens = await service.exchange_code(
        code="code-1",
        client_id="docmind-capacitor",
        redirect_uri="docmind://auth/callback",
        code_verifier="verifier-1234567890",
    )

    assert tokens["access_token"] == "access"
    assert tokens["id_token"]
    assert record.consumed is True


@pytest.mark.asyncio
async def test_mobile_refresh_tokens_returns_new_id_token(monkeypatch):
    user = SimpleNamespace(
        id="user-1",
        tenant_id="tenant-1",
        username="demo",
        email="demo@example.com",
        email_verified=True,
        role="ADMIN",
        is_active=True,
        department="信息办",
    )
    db = FakeDB([user])
    service = MobileOAuthService(db)

    async def fake_refresh(_refresh_token: str):
        return {
            "access_token": __import__("jose").jwt.encode(
                {
                    "sub": "user-1",
                    "tenant_id": "tenant-1",
                    "role": "ADMIN",
                    "type": "access",
                    "exp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                    + __import__("datetime").timedelta(minutes=30),
                },
                __import__("app.config", fromlist=["settings"]).settings.jwt_secret_key,
                algorithm=__import__("app.config", fromlist=["settings"]).settings.jwt_algorithm,
            ),
            "refresh_token": "refresh-2",
            "token_type": "bearer",
            "expires_in": 1800,
        }

    monkeypatch.setattr(service.auth_service, "refresh", fake_refresh)

    tokens = await service.refresh_tokens(
        refresh_token="refresh-1",
        client_id="docmind-capacitor",
    )

    assert tokens["refresh_token"] == "refresh-2"
    assert tokens["id_token"]
    assert tokens["scope"] == "openid profile email offline_access"


def test_mobile_status_reports_miniapp_bootstrap(monkeypatch):
    db = FakeDB([])
    service = MobileOAuthService(db)

    monkeypatch.setattr(settings, "auth_mobile_oauth_enabled", True)
    monkeypatch.setattr(settings, "auth_mobile_oauth_clients", "docmind-capacitor,docmind-miniapp")
    monkeypatch.setattr(
        settings,
        "auth_mobile_oauth_redirect_uris",
        "docmind://auth/callback,https://servicewechat.com/docmind/callback",
    )
    monkeypatch.setattr(settings, "auth_mobile_authorization_code_expire_minutes", 5)

    payload = service.status("https://docmind.example.com")

    assert payload["ready"] is True
    assert payload["miniapp"]["ready"] is True
    assert payload["miniapp"]["clients"] == ["docmind-miniapp"]
    assert payload["miniapp"]["redirect_uris"] == ["https://servicewechat.com/docmind/callback"]
    assert payload["miniapp"]["recommended_api_base"] == "https://docmind.example.com/api/v1"
    assert payload["miniapp"]["recommended_ws_base"] == "wss://docmind.example.com/api/v1/ws/chat"


def test_mobile_bootstrap_document_exposes_runtime_endpoints(monkeypatch):
    db = FakeDB([])
    service = MobileOAuthService(db)

    monkeypatch.setattr(settings, "auth_mobile_oauth_enabled", True)
    monkeypatch.setattr(settings, "auth_mobile_oauth_clients", "docmind-miniapp")
    monkeypatch.setattr(settings, "auth_mobile_oauth_redirect_uris", "https://servicewechat.com/docmind/callback")

    payload = service.bootstrap_document("https://docmind.example.com")

    assert payload["api_base"] == "https://docmind.example.com/api/v1"
    assert payload["ws_base"] == "wss://docmind.example.com/api/v1/ws/chat"
    assert payload["endpoints"]["chat_message"].endswith("/api/v1/chat/message")
    assert payload["auth"]["miniapp"]["ready"] is True
