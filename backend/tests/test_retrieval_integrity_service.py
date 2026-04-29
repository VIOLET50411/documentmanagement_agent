from types import SimpleNamespace

import pytest

from app.services.retrieval_integrity_service import RetrievalIntegrityService


class FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeDB:
    def __init__(self, scalars, rows):
        self.scalars = list(scalars)
        self.rows = rows

    async def scalar(self, _query):
        return self.scalars.pop(0)

    async def execute(self, _query):
        return FakeRows(self.rows)


@pytest.mark.asyncio
async def test_retrieval_integrity_marks_warning_only_backends_as_non_blocking(monkeypatch):
    db = FakeDB(
        scalars=[1, 2],
        rows=[
            ("chunk-1", "doc-1", "travel reimbursement policy", "expense", "travel handbook"),
            ("chunk-2", "doc-1", "invoice process", "invoice", "travel handbook"),
        ],
    )
    service = RetrievalIntegrityService(db)

    class FakeES:
        def health(self):
            return {"available": True, "documents": 2}

        async def search(self, *_args, **_kwargs):
            return [{"chunk_id": "chunk-1", "doc_id": "doc-1"}, {"chunk_id": "chunk-2", "doc_id": "doc-1"}]

    class FakeMilvus:
        dim = 8

        def health(self):
            return {"available": False, "entities": 0}

        async def search(self, *_args, **_kwargs):
            return []

    class FakeNeo4j:
        def health(self):
            return {"available": False, "relationships": 0}

        def close(self):
            return None

    class FakeEmbedder:
        def __init__(self, *args, **kwargs):
            self.dim = 8

        def remote_health(self):
            return {"available": False}

        def embed_query(self, query):
            return {"dense": [0.1] * 8, "sparse": {query: 1.0}}

    monkeypatch.setattr("app.services.retrieval_integrity_service.ESClient", FakeES)
    monkeypatch.setattr("app.services.retrieval_integrity_service.MilvusClient", FakeMilvus)
    monkeypatch.setattr("app.services.retrieval_integrity_service.Neo4jClient", FakeNeo4j)
    monkeypatch.setattr("app.services.retrieval_integrity_service.DocumentEmbedder", FakeEmbedder)

    result = await service.evaluate("tenant-1", sample_size=2)

    assert result["score"] == 66.67
    assert result["healthy"] is True
    assert all(item["severity"] != "critical" for item in result["critical_blockers"])
    assert result["stats"]["backend_health"]["milvus"]["available"] is False
    assert result["mode"] == "keyword_graph_default"


@pytest.mark.asyncio
async def test_retrieval_integrity_health_timeout_returns_degraded_backend():
    db = FakeDB(scalars=[0, 0], rows=[])
    service = RetrievalIntegrityService(db)

    def slow_health():
        raise RuntimeError("boom")

    result = await service._run_sync_health(slow_health, backend="milvus")

    assert result["available"] is False
    assert result["backend"] == "milvus"
    assert result["status"] == "degraded"
