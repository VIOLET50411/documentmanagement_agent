import pytest

from app.retrieval.semantic_cache import SemanticCache
from app.security.watermark import Watermarker


class FakeRedis:
    def __init__(self):
        self.storage = {}
        self.sets = {}

    async def get(self, key):
        return self.storage.get(key)

    async def set(self, key, value, ex=None):
        self.storage[key] = value

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def expire(self, key, seconds):
        return None

    async def delete(self, *keys):
        for key in keys:
            self.storage.pop(key, None)
            self.sets.pop(key, None)


@pytest.mark.asyncio
async def test_semantic_cache_put_and_get_roundtrip(monkeypatch):
    monkeypatch.setattr("app.retrieval.semantic_cache.settings.semantic_cache_enabled", True)
    cache = SemanticCache(FakeRedis())
    async def fake_upsert(*args, **kwargs):
        return None
    monkeypatch.setattr(cache, "_upsert_vector_entry", fake_upsert)

    await cache.put("年假制度", "答案文本", [{"doc_id": "1"}], user_id="user-1")
    payload = await cache.get("年假制度", user_id="user-1")

    assert payload["answer"] == "答案文本"
    assert payload["citations"][0]["doc_id"] == "1"


@pytest.mark.asyncio
async def test_semantic_cache_supports_vector_lookup(monkeypatch):
    monkeypatch.setattr("app.retrieval.semantic_cache.settings.semantic_cache_enabled", True)
    cache = SemanticCache(FakeRedis())
    async def fake_upsert(*args, **kwargs):
        return None
    monkeypatch.setattr(cache, "_upsert_vector_entry", fake_upsert)

    await cache.put("差旅报销制度", "规则说明", [{"doc_id": "doc-1"}], user_id="user-1")
    exact_key = cache._build_key("差旅报销制度", "user-1")
    async def fake_match(query, user_id=None):
        return exact_key
    monkeypatch.setattr(cache, "_search_vector_match", fake_match)

    payload = await cache.get("差旅报销规则", user_id="user-1")

    assert payload["answer"] == "规则说明"
    assert payload["cache_key"] == exact_key


@pytest.mark.asyncio
async def test_semantic_cache_strips_watermark(monkeypatch):
    monkeypatch.setattr("app.retrieval.semantic_cache.settings.semantic_cache_enabled", True)
    cache = SemanticCache(FakeRedis())
    async def fake_upsert(*args, **kwargs):
        return None
    monkeypatch.setattr(cache, "_upsert_vector_entry", fake_upsert)
    marked = Watermarker().inject("制度答案", "user-1", timestamp="2026-01-01T00:00:00")

    await cache.put("测试问题", marked, [], user_id="user-1")
    payload = await cache.get("测试问题", user_id="user-1")

    assert payload["answer"] == "制度答案"


@pytest.mark.asyncio
async def test_semantic_cache_can_invalidate_by_doc(monkeypatch):
    monkeypatch.setattr("app.retrieval.semantic_cache.settings.semantic_cache_enabled", True)
    redis = FakeRedis()
    cache = SemanticCache(redis)
    deleted_keys = []
    async def fake_upsert(*args, **kwargs):
        return None
    async def fake_delete(keys):
        deleted_keys.extend(keys)
    monkeypatch.setattr(cache, "_upsert_vector_entry", fake_upsert)
    monkeypatch.setattr(cache, "_delete_vector_entries", fake_delete)

    await cache.put("报销制度", "答案文本", [{"doc_id": "doc-1"}], user_id="user-1")
    assert await cache.get("报销制度", user_id="user-1")

    deleted = await cache.invalidate_by_doc("doc-1")
    assert deleted == 1
    assert deleted_keys
    assert await cache.get("报销制度", user_id="user-1") is None
