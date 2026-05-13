from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.middleware.rate_limit import rate_limit_check
from app.dependencies import init_minio, init_redis


class FailingRedisClient:
    async def ping(self):
        raise OSError("redis unavailable")

    async def aclose(self):
        return None


class ErroringCounterRedis:
    async def incr(self, _key: str):
        raise OSError("redis unavailable")

    async def expire(self, _key: str, _window: int):
        return None


@pytest.mark.asyncio
async def test_init_redis_disables_client_when_ping_fails(monkeypatch):
    fake_state = SimpleNamespace()
    fake_app = SimpleNamespace(state=fake_state)

    monkeypatch.setattr("app.dependencies.Redis.from_url", lambda *_args, **_kwargs: FailingRedisClient())

    await init_redis(fake_app)

    assert getattr(fake_app.state, "redis", "missing") is None


@pytest.mark.asyncio
async def test_rate_limit_check_fails_open_when_redis_errors(monkeypatch):
    monkeypatch.setattr("app.api.middleware.rate_limit.get_redis", lambda: ErroringCounterRedis())

    await rate_limit_check(None, "chat:user-1", limit=1, window=60)


@pytest.mark.asyncio
async def test_init_minio_does_not_probe_bucket_on_startup(monkeypatch):
    fake_state = SimpleNamespace()
    fake_app = SimpleNamespace(state=fake_state)

    class FakeMinio:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def bucket_exists(self, _bucket: str):
            raise AssertionError("startup should not call bucket_exists")

    monkeypatch.setattr("app.dependencies.Minio", FakeMinio)

    await init_minio(fake_app)

    assert isinstance(fake_app.state.minio_client, FakeMinio)
