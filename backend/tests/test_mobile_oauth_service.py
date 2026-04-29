from __future__ import annotations

from types import SimpleNamespace

import pytest

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
