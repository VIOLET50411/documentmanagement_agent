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


def test_graph_extractor_filters_generic_notice_entities():
    extractor = GraphExtractor()

    entities = extractor._extract_entities(
        "关于印发《西南大学固定资产管理办法》的通知 各单位 第一章 2019 424号 西南大学 国有资产管理处 现印发给你们 请遵照执行"
    )

    assert "关于印发" not in entities
    assert "各单位" not in entities
    assert "第一章" not in entities
    assert "2019" not in entities
    assert "现印发给你们" not in entities
    assert "请遵照执行" not in entities
    assert "西南大学" in entities
    assert "国有资产管理处" in entities


def test_graph_extractor_single_entity_falls_back_to_document_title():
    extractor = GraphExtractor()

    triples = extractor._extract_relationships(
        ["国有资产管理处"],
        "国有资产管理处负责固定资产管理。",
        {
            "doc_id": "doc-3",
            "tenant_id": "default",
            "section_title": "第一章",
            "title": "西南大学固定资产管理办法",
        },
    )

    assert triples
    assert triples[0]["source"] == "国有资产管理处"
    assert triples[0]["target"] == "西南大学固定资产管理办法"


def test_graph_extractor_filters_administrative_fragment_entities():
    extractor = GraphExtractor()

    entities = extractor._extract_entities(
        "处置结果于每季度终了后的10个工作日报教育部备案。"
        "单项价值在800万元以上的，由学校审核后报教育部审核。"
        "专项资金应遵循项目申报、预算评审、专款专用、绩效评价等管理流程。"
    )

    assert "每季度终了后的10" not in entities
    assert "个工作日报教育部备案" not in entities
    assert "由学校审核后报教育部审核" not in entities
    assert "专款专用" not in entities


def test_graph_extractor_filters_generic_action_terms():
    extractor = GraphExtractor()

    entities = extractor._extract_entities(
        "专项资金按照以下分类归口管理，相关审批手续应按规定执行。"
    )

    assert "按照" not in entities
    assert "归口管理" not in entities
    assert "审批" not in entities


def test_graph_extractor_filters_clause_and_budget_phrase_entities():
    extractor = GraphExtractor()

    entities = extractor._extract_entities(
        "对于未达使用年限的固定资产，原则上不予处置。"
        "单价在10万元以下，批量在20万元以下家具及其他固定资产的验收由使用单位组织。"
        "资产处置取得的收益留归学校，纳入学校预算，统一管理。"
    )

    assert "对于未达使用年限的固定资产" not in entities
    assert "万元以下" not in entities
    assert "留归学校" not in entities
    assert "纳入学校预算" not in entities
    assert "统一管理" not in entities


def test_graph_extractor_does_not_keep_long_clause_just_because_it_ends_like_department():
    extractor = GraphExtractor()

    entities = extractor._extract_entities(
        "经归口管理部门鉴定同意报废后交国有资产管理处，并按规定办理后续手续。"
    )

    assert "经归口管理部门鉴定同意报废后交国有资产管理处" not in entities


def test_graph_extractor_filters_generic_nouns_and_clause_heads_without_harming_real_orgs():
    extractor = GraphExtractor()

    entities = extractor._extract_entities(
        "国有资产管理处负责固定资产综合管理。"
        "项目经审批后执行。"
        "由学校财经领导小组会议审议通过的项目纳入项目库。"
        "组织编制修编校园建设总体规划。"
    )

    assert "国有资产管理处" in entities
    assert "资产" not in entities
    assert "项目" not in entities
    assert "由学校" not in entities
    assert "修编" not in entities
    assert "报教育部" not in entities
    assert "设计" not in entities
