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

    assert searcher._should_include_graph("谁负责差旅审批流程")
    assert searcher._should_include_graph("制度上下级关联关系是什么")
