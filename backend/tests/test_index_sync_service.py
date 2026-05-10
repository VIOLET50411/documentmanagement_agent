from types import SimpleNamespace

import pytest

from app.services.index_sync_service import IndexSyncService


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, docs, chunks):
        self._docs = docs
        self._chunks = chunks
        self._calls = 0

    async def execute(self, _query):
        self._calls += 1
        if self._calls == 1:
            return _Result(self._docs)
        return _Result(self._chunks)


class _Minio:
    def __init__(self, missing_paths=None):
        self.missing_paths = set(missing_paths or [])

    def stat_object(self, _bucket, object_path):
        if object_path in self.missing_paths:
            raise RuntimeError("missing object")
        return {"path": object_path}


@pytest.mark.asyncio
async def test_audit_tenant_consistency_reports_missing_storage_and_indexes(monkeypatch):
    now = SimpleNamespace(isoformat=lambda: "2026-05-10T00:00:00+00:00")
    doc_ok = SimpleNamespace(
        id="doc-1",
        title="差旅制度",
        status="ready",
        minio_path="ok/doc-1.pdf",
        updated_at=now,
    )
    doc_broken = SimpleNamespace(
        id="doc-2",
        title="合同制度",
        status="ready",
        minio_path="missing/doc-2.pdf",
        updated_at=now,
    )
    doc_no_chunk = SimpleNamespace(
        id="doc-3",
        title="空文档",
        status="ready",
        minio_path="ok/doc-3.pdf",
        updated_at=now,
    )
    chunk_ok = SimpleNamespace(doc_id="doc-1", section_title="审批", content="差旅制度要求先审批后报销。", created_at=now)
    chunk_broken = SimpleNamespace(doc_id="doc-2", section_title="签订", content="合同制度说明签订流程。", created_at=now)

    class FakeES:
        async def search(self, query, filters, top_k=5):
            if "合同制度" in query:
                return []
            return [{"doc_id": "doc-1", "document_title": "差旅制度"}]

        def health(self):
            return {"available": True, "documents": 2}

        async def close(self):
            return None

    class FakeMilvus:
        def __init__(self, dim=None):
            self.dim = dim or 12

        async def search(self, query_embedding, filters, top_k=8):
            if "合同制度" in query_embedding.get("query_text", ""):
                return []
            return [{"doc_id": "doc-1", "document_title": "差旅制度"}]

        def health(self):
            return {"available": True, "entities": 2}

    class FakeEmbedder:
        def __init__(self, dense_dim=12):
            self.dense_dim = dense_dim

        def local_embed_query(self, query):
            return {"dense": [0.1] * self.dense_dim, "query_text": query}

        def embed_query(self, query):
            return {"dense": [0.1] * self.dense_dim, "query_text": query}

    class FakeNeo4j:
        def health(self):
            return {"available": True, "relationships": 0}

        def close(self):
            return None

    monkeypatch.setattr("app.services.index_sync_service.ESClient", FakeES)
    monkeypatch.setattr("app.services.index_sync_service.MilvusClient", FakeMilvus)
    monkeypatch.setattr("app.services.index_sync_service.DocumentEmbedder", FakeEmbedder)
    monkeypatch.setattr("app.services.index_sync_service.Neo4jClient", FakeNeo4j)

    service = IndexSyncService(_DB([doc_ok, doc_broken, doc_no_chunk], [chunk_ok, chunk_broken]))
    report = await service.audit_tenant_consistency("tenant-1", limit=10, minio_client=_Minio({"missing/doc-2.pdf"}))

    assert report["stats"]["documents"] == 3
    assert report["stats"]["ready_chunks"] == 2
    assert report["stats"]["docs_without_chunks"] == 1
    assert report["stats"]["minio_missing_docs"] == 1
    assert report["stats"]["es_missing_docs"] == 1
    assert report["stats"]["milvus_missing_docs"] == 1
    assert report["samples"]["docs_without_chunks"][0]["doc_id"] == "doc-3"
    assert report["samples"]["minio_missing_docs"][0]["doc_id"] == "doc-2"
