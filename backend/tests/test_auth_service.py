from types import SimpleNamespace

import pytest
from jose import jwt

from app.config import settings
from app.services.auth_service import AuthService


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, user):
        self.user = user

    async def execute(self, _query):
        return FakeResult(self.user)


@pytest.mark.asyncio
async def test_create_tokens_contains_access_claims():
    user = SimpleNamespace(id="user-1", tenant_id="tenant-1", role="EMPLOYEE")
    service = AuthService(db=None)

    tokens = service.create_tokens(user)
    payload = jwt.decode(
        tokens["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )

    assert payload["sub"] == "user-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["role"] == "EMPLOYEE"
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_refresh_returns_new_tokens_for_active_user():
    user = SimpleNamespace(id="user-1", tenant_id="tenant-1", role="EMPLOYEE", is_active=True)
    service = AuthService(db=FakeDB(user))
    refresh_token = service.create_tokens(user)["refresh_token"]

    refreshed = await service.refresh(refresh_token)

    assert refreshed["token_type"] == "bearer"
    assert refreshed["access_token"]
    assert refreshed["refresh_token"]
