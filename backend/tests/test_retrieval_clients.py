import asyncio
from unittest.mock import MagicMock

import pytest

from app.retrieval.es_client import ESClient
from app.retrieval.milvus_client import MilvusClient
from app.retrieval.neo4j_client import Neo4jClient


@pytest.mark.asyncio
async def test_milvus_search_returns_empty_when_timeout(monkeypatch):
    client = MilvusClient(dim=8)
    client.available = True

    async def fake_to_thread(*_args, **_kwargs):
        await asyncio.sleep(0)
        return []

    async def fake_wait_for(awaitable, *_args, **_kwargs):
        await awaitable
        raise asyncio.TimeoutError()

    monkeypatch.setattr("app.retrieval.milvus_client.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("app.retrieval.milvus_client.asyncio.wait_for", fake_wait_for)

    result = await client.search({"dense": [0.1] * 8}, {"tenant_id": "tenant-1"}, top_k=5)

    assert result == []
    assert client.available is False


def test_milvus_health_returns_degraded_on_runtime_error(monkeypatch):
    client = MilvusClient(dim=8)
    client.available = True
    monkeypatch.setattr(client, "_ensure_available", lambda: True)
    monkeypatch.setattr(client, "_get_collection", lambda: (_ for _ in ()).throw(RuntimeError("milvus down")))

    result = client.health()

    assert result["available"] is False
    assert result["status"] == "degraded"
    assert "milvus down" in result["error"]


def test_milvus_health_prefers_live_row_count(monkeypatch):
    client = MilvusClient(dim=8)
    client.available = True

    class FakeIterator:
        def __init__(self):
            self._batches = [[{"chunk_id": "a"}] * 2, [{"chunk_id": "b"}], []]
            self.closed = False

        def next(self):
            return self._batches.pop(0)

        def close(self):
            self.closed = True

    class FakeCollection:
        num_entities = 9

        def __init__(self):
            self.iterator = FakeIterator()

        def load(self, timeout=None):
            self.timeout = timeout

        def query_iterator(self, **kwargs):
            self.kwargs = kwargs
            return self.iterator

    collection = FakeCollection()
    monkeypatch.setattr(client, "_ensure_available", lambda: True)
    monkeypatch.setattr(client, "_get_collection", lambda: collection)

    result = client.health()

    assert result["available"] is True
    assert result["entities"] == 3
    assert result["raw_entities"] == 9
    assert collection.kwargs["expr"] == 'chunk_id != ""'
    assert collection.iterator.closed is True


def test_milvus_lexical_rerank_uses_iterator_candidates_beyond_first_page():
    client = MilvusClient(dim=8)

    class FakeIterator:
        def __init__(self):
            self._batches = [
                [{"chunk_id": "a-1", "doc_id": "doc-a", "document_title": "其他制度", "section_title": "概述", "snippet": "无关内容"}],
                [{"chunk_id": "target-1", "doc_id": "doc-target", "document_title": "西南大学2023年度部门预算.html", "section_title": "信息公开", "snippet": "西南大学2023年度部门预算"}],
                [],
            ]
            self.closed = False

        def next(self):
            return self._batches.pop(0)

        def close(self):
            self.closed = True

    class FakeCollection:
        def __init__(self):
            self.iterator = FakeIterator()

        def query_iterator(self, **kwargs):
            self.kwargs = kwargs
            return self.iterator

    reranked = client._lexical_rerank(
        collection=FakeCollection(),
        expr='tenant_id == "default"',
        dense_hits=[],
        dense_scores={},
        query_embedding={"sparse": {"西南大学2023年度部门预算": 1.0, "信息公开": 1.0}},
        top_k=5,
    )

    assert reranked[0]["doc_id"] == "doc-target"


def test_es_health_returns_degraded_on_transport_error(monkeypatch):
    client = ESClient()
    monkeypatch.setattr(client, "_ensure_index_sync", lambda: (_ for _ in ()).throw(RuntimeError("es down")))

    result = client.health()

    assert result["available"] is False
    assert result["documents"] == 0
    assert "es down" in result["error"]


def test_es_delete_by_doc_uses_keyword_field_directly(monkeypatch):
    client = ESClient()
    calls = {}

    class FakeSyncClient:
        def delete_by_query(self, **kwargs):
            calls.update(kwargs)
            return {"deleted": 3}

    monkeypatch.setattr(client, "_ensure_index_sync", lambda: None)
    client.sync_client = FakeSyncClient()

    deleted = client.delete_by_doc("doc-1")

    assert deleted == 3
    assert calls["query"] == {"term": {"doc_id": "doc-1"}}


def test_es_delete_by_tenant_uses_tenant_term(monkeypatch):
    client = ESClient()
    calls = {}

    class FakeSyncClient:
        def delete_by_query(self, **kwargs):
            calls.update(kwargs)
            return {"deleted": 7}

    monkeypatch.setattr(client, "_ensure_index_sync", lambda: None)
    client.sync_client = FakeSyncClient()

    deleted = client.delete_by_tenant("tenant-1")

    assert deleted == 7
    assert calls["query"] == {"term": {"tenant_id": "tenant-1"}}


def test_milvus_delete_by_tenant_uses_tenant_expr(monkeypatch):
    client = MilvusClient(dim=8)
    client.available = True
    calls = {}

    class FakeResponse:
        delete_count = 5

    class FakeCollection:
        def delete(self, **kwargs):
            calls.update(kwargs)
            return FakeResponse()

        def flush(self, timeout=None):
            calls["flush_timeout"] = timeout

        def compact(self):
            calls["compact"] = True

    monkeypatch.setattr(client, "_ensure_available", lambda: True)
    monkeypatch.setattr(client, "_get_collection", lambda: FakeCollection())

    deleted = client.delete_by_tenant("tenant-1")

    assert deleted == 5
    assert calls["expr"] == 'tenant_id == "tenant-1"'
    assert calls["compact"] is True


def test_neo4j_delete_by_tenant_removes_related_edges():
    client = Neo4jClient.__new__(Neo4jClient)

    class FakeResult:
        def single(self):
            return {"count": 11}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, query, **kwargs):
            self.query = query
            self.kwargs = kwargs
            return FakeResult()

    fake_session = FakeSession()
    driver = MagicMock()
    driver.session.return_value = fake_session
    client.driver = driver

    deleted = client.delete_by_tenant("tenant-1")

    assert deleted == 11
    assert "tenant_id: $tenant_id" in fake_session.query
    assert fake_session.kwargs == {"tenant_id": "tenant-1"}


def test_neo4j_health_returns_degraded_on_runtime_error():
    client = Neo4jClient.__new__(Neo4jClient)
    driver = MagicMock()
    driver.session.side_effect = RuntimeError("neo4j down")
    client.driver = driver

    result = client.health()

    assert result["available"] is False
    assert result["relationships"] == 0
    assert "neo4j down" in result["error"]
