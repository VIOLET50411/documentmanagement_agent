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


def test_es_health_returns_degraded_on_transport_error(monkeypatch):
    client = ESClient()
    monkeypatch.setattr(client, "_ensure_index_sync", lambda: (_ for _ in ()).throw(RuntimeError("es down")))

    result = client.health()

    assert result["available"] is False
    assert result["documents"] == 0
    assert "es down" in result["error"]


def test_neo4j_health_returns_degraded_on_runtime_error():
    client = Neo4jClient.__new__(Neo4jClient)
    driver = MagicMock()
    driver.session.side_effect = RuntimeError("neo4j down")
    client.driver = driver

    result = client.health()

    assert result["available"] is False
    assert result["relationships"] == 0
    assert "neo4j down" in result["error"]
