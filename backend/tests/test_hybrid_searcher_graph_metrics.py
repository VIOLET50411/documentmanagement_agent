from types import SimpleNamespace

import pytest

from app.retrieval.hybrid_searcher import HybridSearcher


@pytest.mark.asyncio
async def test_hybrid_search_records_graph_metrics_for_relationship_query(monkeypatch):
    searcher = HybridSearcher()
    calls: list[dict] = []

    class FakeObservability:
        def __init__(self, _redis):
            pass

        async def record(self, tenant_id, backend, **kwargs):
            calls.append({"tenant_id": tenant_id, "backend": backend, **kwargs})

    async def fake_keyword(*args, **kwargs):
        return []

    async def fake_rerank(_query, fused, top_k, tenant_key):
        return fused[:top_k]

    async def fake_graph_traverse(_self, *, query, user, db, top_k):
        assert query == "谁负责差旅审批流程"
        assert user.tenant_id == "default"
        return [
            {
                "doc_id": "doc-1",
                "chunk_id": "chunk-1",
                "document_title": "差旅审批制度.pdf",
                "snippet": "部门负责人负责差旅审批。",
                "score": 1.0,
                "source_type": "graph",
            }
        ]

    monkeypatch.setattr("app.retrieval.hybrid_searcher.RetrievalObservabilityService", FakeObservability)
    monkeypatch.setattr("app.retrieval.hybrid_searcher.get_redis", lambda: object())
    monkeypatch.setattr(searcher, "_search_keyword_path", fake_keyword)
    monkeypatch.setattr(searcher.reranker, "rerank", fake_rerank)
    monkeypatch.setattr("app.retrieval.hybrid_searcher.GraphSearcher.traverse", fake_graph_traverse)

    user = SimpleNamespace(tenant_id="default", level=9, department="Platform", role="ADMIN")

    results = await searcher.search("谁负责差旅审批流程", user=user, top_k=5, search_type="hybrid", db=object())

    assert len(results) == 1
    assert any(item["backend"] == "graph" for item in calls)
    graph_call = next(item for item in calls if item["backend"] == "graph")
    assert graph_call["tenant_id"] == "default"
    assert graph_call["success"] is True
    assert graph_call["empty"] is False
