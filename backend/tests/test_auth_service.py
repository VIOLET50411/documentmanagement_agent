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
        self.deleted = None

    async def execute(self, _query):
        return FakeResult(self.user)

    async def flush(self):
        return None

    async def delete(self, value):
        self.deleted = value


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


@pytest.mark.asyncio
async def test_admin_update_user_updates_role_and_status():
    user = SimpleNamespace(
        id="user-2",
        tenant_id="tenant-1",
        username="member_a",
        role="EMPLOYEE",
        department="研发",
        level=2,
        is_active=True,
        email_verified=False,
    )

    class FakeUpdateDB:
        def __init__(self):
            self.calls = 0

        async def execute(self, _query):
            self.calls += 1
            if self.calls == 1:
                return FakeResult(user)
            return FakeResult(None)

        async def flush(self):
            return None

    service = AuthService(db=FakeUpdateDB())
    updated = await service.admin_update_user(
        tenant_id="tenant-1",
        actor_id="admin-1",
        user_id="user-2",
        username="member_b",
        role="MANAGER",
        department="运营",
        level=5,
        is_active=False,
        email_verified=True,
    )

    assert updated.username == "member_b"
    assert updated.role == "MANAGER"
    assert updated.department == "运营"
    assert updated.level == 5
    assert updated.is_active is False
    assert updated.email_verified is True


@pytest.mark.asyncio
async def test_admin_update_user_blocks_self_demotion():
    user = SimpleNamespace(
        id="admin-1",
        tenant_id="tenant-1",
        username="admin_demo",
        role="ADMIN",
        department="平台",
        level=9,
        is_active=True,
        email_verified=True,
    )

    service = AuthService(db=FakeDB(user))

    with pytest.raises(ValueError, match="不能移除当前管理员的管理员角色"):
        await service.admin_update_user(
            tenant_id="tenant-1",
            actor_id="admin-1",
            user_id="admin-1",
            role="EMPLOYEE",
        )


@pytest.mark.asyncio
async def test_admin_reset_password_returns_temporary_password():
    user = SimpleNamespace(
        id="user-3",
        tenant_id="tenant-1",
        username="member_c",
        role="EMPLOYEE",
        department="运营",
        level=2,
        is_active=True,
        email_verified=True,
        hashed_password="old",
    )

    service = AuthService(db=FakeDB(user))
    updated_user, temporary_password = await service.admin_reset_password(
        tenant_id="tenant-1",
        actor_id="admin-1",
        user_id="user-3",
    )

    assert updated_user.username == "member_c"
    assert temporary_password
    assert temporary_password != "old"
    assert user.hashed_password != "old"


@pytest.mark.asyncio
async def test_admin_reset_password_blocks_self_reset():
    user = SimpleNamespace(
        id="admin-1",
        tenant_id="tenant-1",
        username="admin_demo",
        role="ADMIN",
        department="平台",
        level=9,
        is_active=True,
        email_verified=True,
        hashed_password="old",
    )

    service = AuthService(db=FakeDB(user))

    with pytest.raises(ValueError, match="不能重置当前管理员自己的密码"):
        await service.admin_reset_password(
            tenant_id="tenant-1",
            actor_id="admin-1",
            user_id="admin-1",
        )


@pytest.mark.asyncio
async def test_admin_delete_user_marks_user_deleted():
    user = SimpleNamespace(
        id="user-4",
        tenant_id="tenant-1",
        username="member_d",
        role="EMPLOYEE",
        department="运营",
        level=2,
        is_active=True,
        email_verified=True,
    )
    db = FakeDB(user)
    service = AuthService(db=db)

    deleted = await service.admin_delete_user(
        tenant_id="tenant-1",
        actor_id="admin-1",
        user_id="user-4",
    )

    assert deleted.username == "member_d"
    assert db.deleted is user


@pytest.mark.asyncio
async def test_admin_delete_user_blocks_self_delete():
    user = SimpleNamespace(
        id="admin-1",
        tenant_id="tenant-1",
        username="admin_demo",
        role="ADMIN",
        department="平台",
        level=9,
        is_active=True,
        email_verified=True,
    )
    service = AuthService(db=FakeDB(user))

    with pytest.raises(ValueError, match="不能删除当前管理员自己"):
        await service.admin_delete_user(
            tenant_id="tenant-1",
            actor_id="admin-1",
            user_id="admin-1",
        )
