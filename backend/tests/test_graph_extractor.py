from app.ingestion.graph_extractor import GraphExtractor


def test_graph_extractor_disables_llm_after_first_failure(monkeypatch):
    extractor = GraphExtractor()
    calls = {"count": 0}

    class FakeLLM:
        is_rule_only = False

    class DummyNeo4j:
        def upsert_triples(self, triples):
            return None

        def close(self):
            return None

    monkeypatch.setattr("app.ingestion.graph_extractor.LLMService", lambda: FakeLLM())
    monkeypatch.setattr("app.ingestion.graph_extractor.Neo4jClient", DummyNeo4j)

    def fake_extract(self, llm, text, chunk):
        calls["count"] += 1
        self._disable_llm_for_run = True
        return None

    monkeypatch.setattr(GraphExtractor, "_extract_with_llm_sync", fake_extract)
    monkeypatch.setattr(GraphExtractor, "_extract_entities", lambda self, text: ["流程", "审批"])

    triples = extractor.extract_and_store_sync(
        [
            {"content": "审批流程说明", "doc_id": "doc-1", "tenant_id": "default", "section_title": "流程"},
            {"content": "继续处理任务", "doc_id": "doc-1", "tenant_id": "default", "section_title": "流程"},
        ]
    )

    assert calls["count"] == 1
    assert extractor._disable_llm_for_run is True
    assert triples


def test_graph_extractor_uses_clean_chinese_heuristics():
    extractor = GraphExtractor()
    triples = extractor._extract_relationships(
        ["财务部", "报销制度", "审批流程"],
        "财务部负责报销审批流程并进行管理。",
        {"doc_id": "doc-2", "tenant_id": "default", "section_title": "制度"},
    )

    assert triples
    assert all(item["relationship"] == "manages" for item in triples)


def test_graph_extractor_extracts_chinese_entities_from_source_literals():
    extractor = GraphExtractor()
    entities = extractor._extract_entities("财务部负责报销审批流程。")

    assert entities
    assert any("财务部" in item for item in entities)
