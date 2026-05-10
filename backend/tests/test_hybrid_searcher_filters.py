import pytest

from app.retrieval.hybrid_searcher import HybridSearcher


def test_filter_synthetic_results_removes_default_test_artifacts():
    searcher = HybridSearcher()

    results = [
        {"document_title": "push-test.csv", "chunk_id": "1"},
        {"document_title": "tmp_ui_upload.csv", "chunk_id": "2"},
        {"document_title": "smoke_1.csv", "chunk_id": "3"},
        {"document_title": "smoke.csv", "chunk_id": "4"},
        {"document_title": "loadtest_4.csv", "chunk_id": "5"},
        {"document_title": "perf_0.csv", "chunk_id": "6"},
        {"document_title": "large.csv", "chunk_id": "7"},
        {"document_title": "差旅审批制度.csv", "chunk_id": "8"},
    ]

    filtered = searcher._filter_synthetic_results(results, query="差旅审批")

    assert [item["chunk_id"] for item in filtered] == ["8"]


def test_filter_synthetic_results_keeps_explicit_title_lookup():
    searcher = HybridSearcher()

    results = [
        {"document_title": "push-test.csv", "chunk_id": "1"},
        {"document_title": "正式制度文档.pdf", "chunk_id": "2"},
    ]

    filtered = searcher._filter_synthetic_results(results, query="请打开 push-test.csv")

    assert [item["chunk_id"] for item in filtered] == ["1", "2"]


def test_should_include_graph_for_relationship_question():
    searcher = HybridSearcher()

    assert searcher._should_include_graph("谁负责差旅审批流程？")
    assert searcher._should_include_graph("制度上下级关联关系是什么？")


def test_extract_explicit_titles_from_query():
    searcher = HybridSearcher()

    titles = searcher._extract_explicit_titles("请根据《西南大学新进教职工合同签订常见问题》概括试用期规则")

    assert titles == ["西南大学新进教职工合同签订常见问题"]


def test_prefer_explicit_title_matches_when_named_document_exists():
    searcher = HybridSearcher()

    results = [
        {"document_title": "西南大学2023年度决算公开", "chunk_id": "1"},
        {"document_title": "西南大学2023年度部门预算", "chunk_id": "2"},
        {"document_title": "西南大学2023年度部门预算（附件）", "chunk_id": "3"},
    ]

    filtered = searcher._prefer_explicit_title_matches(results, query="请根据《西南大学2023年度部门预算》概括主要内容")

    assert [item["chunk_id"] for item in filtered] == ["2", "3"]


@pytest.mark.asyncio
async def test_search_keyword_path_merges_db_results_for_explicit_title(monkeypatch):
    searcher = HybridSearcher()

    class FakeChunk:
        doc_id = "doc-2023"
        id = "chunk-11"
        content = "三、部门预算情况说明 我校2023年收支总预算557,259.13万元，其中本年收入预算403,484.64万元。"
        page_number = 11
        section_title = "预算情况说明"

    class FakeDocument:
        title = "西南大学2023年度部门预算.html"
        department = "Platform"
        access_level = 1

    class FakeRows:
        def all(self):
            return [(FakeChunk(), FakeDocument(), 42.0)]

    class FakeDB:
        async def execute(self, _query):
            return FakeRows()

    async def fake_es_search(**_kwargs):
        return [
            {
                "doc_id": "doc-2023",
                "chunk_id": "chunk-cover",
                "document_title": "西南大学2023年度部门预算.html",
                "snippet": "西南大学 2023 年度部门预算 2023 年4月",
                "page_number": 1,
                "section_title": "20_swu_2023_department_budget__download.jsp",
                "score": 50.0,
                "source_type": "es",
                "department": "Platform",
            }
        ]

    monkeypatch.setattr(searcher.es_client, "search", fake_es_search)

    results = await searcher._search_keyword_path(
        FakeDB(),
        {"tenant_id": "default", "access_level": {"$lte": 1}, "department": {"$in": ["Platform", "public"]}},
        "请根据《西南大学2023年度部门预算》概括主要内容",
        searcher._extract_terms("请根据《西南大学2023年度部门预算》概括主要内容"),
        top_k=5,
    )

    assert results[0]["page_number"] == 11
    assert any(item["page_number"] == 1 for item in results)
