import pytest

import app.api.v1.search as search_api
import app.api.v1.admin.system as admin_system


@pytest.mark.asyncio
async def test_search_api_mode_alias_overrides_search_type(monkeypatch):
    calls = {}

    class FakeSearcher:
        async def search(self, *, query, user, top_k, search_type, db):
            calls.update(
                {
                    "query": query,
                    "user": user,
                    "top_k": top_k,
                    "search_type": search_type,
                    "db": db,
                }
            )
            return [{"document_title": "x"}]

    monkeypatch.setattr(search_api, "_searcher", FakeSearcher())

    user = object()
    db = object()
    payload = await search_api.search_documents(
        q="谁负责固定资产管理",
        top_k=3,
        search_type="hybrid",
        mode="graph",
        current_user=user,
        db=db,
    )

    assert calls["search_type"] == "graph"
    assert payload["total"] == 1


@pytest.mark.asyncio
async def test_search_api_uses_search_type_when_mode_missing(monkeypatch):
    calls = {}

    class FakeSearcher:
        async def search(self, *, query, user, top_k, search_type, db):
            calls["search_type"] = search_type
            return []

    monkeypatch.setattr(search_api, "_searcher", FakeSearcher())

    await search_api.search_documents(
        q="预算绩效管理",
        top_k=5,
        search_type="keyword",
        mode=None,
        current_user=object(),
        db=object(),
    )

    assert calls["search_type"] == "keyword"


@pytest.mark.asyncio
async def test_admin_retrieval_debug_returns_rewritten_query(monkeypatch):
    calls = []

    class FakeSearcher:
        async def search(self, *, query, user, top_k, search_type, db):
            calls.append(
                {
                    "query": query,
                    "user": user,
                    "top_k": top_k,
                    "search_type": search_type,
                    "db": db,
                }
            )
            if query == "这个审批怎么走？":
                return [{"document_title": "原始查询命中", "score": 0.61}]
            return [{"document_title": "差旅报销制度", "score": 0.92}]

    async def fake_rewriter(state):
        state["rewritten_query"] = "《差旅报销制度》 审批 流程"
        state["rewrite_source"] = "context_fallback"
        return state

    monkeypatch.setattr(admin_system, "_retrieval_debug_searcher", FakeSearcher())
    monkeypatch.setattr("app.agent.nodes.query_rewriter.query_rewriter", fake_rewriter)

    payload = await admin_system.get_retrieval_debug(
        q="这个审批怎么走？",
        top_k=6,
        search_type="hybrid",
        current_user=object(),
        db=object(),
    )

    assert payload["query"] == "这个审批怎么走？"
    assert payload["rewritten_query"] == "《差旅报销制度》 审批 流程"
    assert payload["rewrite_source"] == "context_fallback"
    assert payload["total"] == 1
    assert payload["original_total"] == 1
    assert payload["original_results"][0]["document_title"] == "原始查询命中"
    assert calls[0]["query"] == "这个审批怎么走？"
    assert calls[1]["query"] == "《差旅报销制度》 审批 流程"
    assert calls[1]["top_k"] == 6
    assert calls[1]["search_type"] == "hybrid"
