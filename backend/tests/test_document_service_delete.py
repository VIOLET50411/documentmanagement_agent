from types import SimpleNamespace

import pytest

from app.services.document_service import DocumentService


class _FakeExecResult:
    def __init__(self, document=None):
        self._document = document

    def scalar_one_or_none(self):
        return self._document


class _FakeDB:
    def __init__(self, document):
        self.document = document
        self.calls = 0
        self.info = {}

    async def execute(self, _stmt):
        self.calls += 1
        if self.calls == 1:
            return _FakeExecResult(self.document)
        return _FakeExecResult()


class _FakeMinio:
    def __init__(self):
        self.removed = []

    def remove_object(self, bucket, path):
        self.removed.append((bucket, path))


@pytest.mark.asyncio
async def test_delete_document_cleans_all_external_backends(monkeypatch):
    document = SimpleNamespace(
        id="doc-1",
        tenant_id="tenant-1",
        uploader_id="user-1",
        minio_path="tenant-1/doc-1/file.pdf",
    )
    user = SimpleNamespace(tenant_id="tenant-1", role="ADMIN", id="user-1")
    db = _FakeDB(document)
    minio = _FakeMinio()
    service = DocumentService(db, minio)

    milvus_deleted = []
    es_deleted = []
    neo4j_deleted = []
    redis_deleted = []

    class FakeMilvus:
        def delete_by_doc(self, doc_id):
            milvus_deleted.append(doc_id)

    class FakeES:
        def delete_by_doc(self, doc_id):
            es_deleted.append(doc_id)

    class FakeNeo4j:
        def delete_by_doc(self, doc_id):
            neo4j_deleted.append(doc_id)

    class FakeRedis:
        async def delete(self, key):
            redis_deleted.append(key)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("app.services.document_service.get_redis", lambda: FakeRedis())
    monkeypatch.setattr("app.services.document_service.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("app.services.document_service.MilvusClient", FakeMilvus, raising=False)
    monkeypatch.setattr("app.retrieval.milvus_client.MilvusClient", FakeMilvus)
    monkeypatch.setattr("app.retrieval.es_client.ESClient", FakeES)
    monkeypatch.setattr("app.retrieval.neo4j_client.Neo4jClient", FakeNeo4j)

    await service.delete_document(doc_id="doc-1", user=user)

    assert db.calls == 3
    assert db.info["has_writes"] is True
    assert minio.removed == [("docmind-documents", "tenant-1/doc-1/file.pdf")]
    assert milvus_deleted == ["doc-1"]
    assert es_deleted == ["doc-1"]
    assert neo4j_deleted == ["doc-1"]
    assert redis_deleted == ["doc_progress:doc-1", "doc_progress_events:doc-1"]
