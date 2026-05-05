import pytest

from app.services.index_sync_service import IndexSyncService


class _FakeResult:
    def all(self):
        return []


class _FakeDB:
    async def execute(self, _query):
        return _FakeResult()


@pytest.mark.asyncio
async def test_reindex_tenant_clears_all_backends_before_rebuild(monkeypatch):
    calls = []

    class FakeESClient:
        def delete_by_tenant(self, tenant_id):
            calls.append(("es", tenant_id))
            return 3

    class FakeMilvusClient:
        def __init__(self, dim=None):
            self.dim = dim

        def delete_by_tenant(self, tenant_id):
            calls.append(("milvus", tenant_id))
            return 4

    class FakeNeo4jClient:
        def delete_by_tenant(self, tenant_id):
            calls.append(("neo4j", tenant_id))
            return 5

    monkeypatch.setattr("app.services.index_sync_service.ESClient", FakeESClient)
    monkeypatch.setattr("app.services.index_sync_service.MilvusClient", FakeMilvusClient)
    monkeypatch.setattr("app.services.index_sync_service.Neo4jClient", FakeNeo4jClient)

    result = await IndexSyncService(_FakeDB()).reindex_tenant("default")

    assert result == {
        "tenant_id": "default",
        "chunk_count": 0,
        "es_indexed": 0,
        "milvus_indexed": 0,
        "graph_triples": 0,
    }
    assert calls == [("es", "default"), ("milvus", "default"), ("neo4j", "default")]
