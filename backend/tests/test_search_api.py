import pytest

import app.api.v1.search as search_api


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
