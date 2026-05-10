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
