import pytest

from app.agent.agents.compliance_agent import ComplianceAgent
from app.agent.agents.data_agent import DataAgent
from app.agent.nodes.intent_router import intent_router
from app.agent.nodes.query_rewriter import query_rewriter
from app.agent.tools.text2sql import Text2SQLTool
from app.retrieval.graph_searcher import GraphSearcher
from app.retrieval.hybrid_searcher import HybridSearcher


class FakeResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class FakeDB:
    def __init__(self, row):
        self.info = {}
        self.row = row

    async def execute(self, _sql, _params=None):
        return FakeResult(self.row)


@pytest.mark.asyncio
async def test_intent_router_detects_statistics():
    state = await intent_router({"query": "当前文档总数是多少？"})
    assert state["intent"] == "statistics"


@pytest.mark.asyncio
async def test_intent_router_detects_compare():
    state = await intent_router({"query": "请比较今年和去年的报销制度区别"})
    assert state["intent"] == "compare"


@pytest.mark.asyncio
async def test_query_rewriter_expands_ambiguous_reference():
    state = await query_rewriter(
        {
            "query": "这个什么时候生效？",
            "messages": [{"role": "user", "content": "2026 差旅报销制度"}],
        }
    )
    assert "差旅报销制度" in state["rewritten_query"]


@pytest.mark.asyncio
async def test_text2sql_tool_handles_document_count(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    tool = Text2SQLTool(FakeDB({"total_documents": 12}))
    tool.db.info["tenant_id"] = "tenant-1"
    result = await tool.generate_and_execute("文档总数是多少？")

    assert result["status"] == "ok"
    assert result["results"][0]["total_documents"] == 12


@pytest.mark.asyncio
async def test_data_agent_formats_statistics_answer(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    agent = DataAgent()
    state = await agent.run(
        {
            "db": FakeDB({"total_documents": 12}),
            "current_user": type("User", (), {"tenant_id": "tenant-1"})(),
            "query": "文档总数是多少？",
            "rewritten_query": "文档总数是多少？",
        }
    )
    assert "统计结论" in state["answer"]
    assert "文档总数" in state["answer"]


@pytest.mark.asyncio
async def test_compliance_agent_formats_answer_with_citations(monkeypatch):
    async def no_llm_answer(*args, **kwargs):
        return None

    class DummySearcher:
        async def search(self, **kwargs):
            return [
                {
                    "doc_id": "doc-1",
                    "document_title": "员工手册",
                    "snippet": "员工每年可享受 10 天年假，需要按流程申请。",
                    "page_number": 3,
                    "section_title": "休假管理",
                    "score": 1.0,
                }
            ]

    monkeypatch.setattr("app.retrieval.hybrid_searcher.HybridSearcher", DummySearcher)
    monkeypatch.setattr(ComplianceAgent, "_try_llm_answer", no_llm_answer)
    agent = ComplianceAgent()
    state = await agent.run(
        {
            "query": "年假制度是什么？",
            "rewritten_query": "年假制度是什么？",
            "current_user": object(),
            "search_type": "hybrid",
            "db": object(),
            "intent": "qa",
        }
    )

    assert "**结论**" in state["answer"]
    assert "### 相关依据" in state["answer"]
    assert state["citations"][0]["doc_title"] == "员工手册"


@pytest.mark.asyncio
async def test_compliance_agent_extracts_table_evidence(monkeypatch):
    async def no_llm_answer(*args, **kwargs):
        return None

    class DummySearcher:
        async def search(self, **kwargs):
            return [
                {
                    "doc_id": "doc-1",
                    "document_title": "请假制度表",
                    "snippet": "| policy | content |\n| --- | --- |\n| travel | 出差前需要提交审批 |\n| leave | 员工每年享有带薪年假，具体天数依据职级确定。|",
                    "page_number": None,
                    "section_title": "未命名章节",
                    "score": 1.0,
                }
            ]

    monkeypatch.setattr("app.retrieval.hybrid_searcher.HybridSearcher", DummySearcher)
    monkeypatch.setattr(ComplianceAgent, "_try_llm_answer", no_llm_answer)
    agent = ComplianceAgent()
    state = await agent.run(
        {
            "query": "年假制度是什么？",
            "rewritten_query": "年假制度是什么？",
            "current_user": object(),
            "search_type": "hybrid",
            "db": object(),
            "intent": "qa",
        }
    )

    assert "带薪年假" in state["answer"]
    assert "travel" not in state["answer"]


@pytest.mark.asyncio
async def test_compliance_agent_formats_compare_table(monkeypatch):
    async def no_llm_answer(*args, **kwargs):
        return None

    class DummySearcher:
        async def search(self, **kwargs):
            return [
                {
                    "doc_id": "doc-1",
                    "document_title": "年假制度",
                    "snippet": "员工转正后可申请年假并按审批流程执行。",
                    "page_number": 2,
                    "section_title": "休假管理",
                    "score": 1.0,
                },
                {
                    "doc_id": "doc-2",
                    "document_title": "差旅制度",
                    "snippet": "差旅报销需附发票与审批单。",
                    "page_number": 4,
                    "section_title": "报销管理",
                    "score": 0.9,
                },
            ]

    monkeypatch.setattr("app.retrieval.hybrid_searcher.HybridSearcher", DummySearcher)
    monkeypatch.setattr(ComplianceAgent, "_try_llm_answer", no_llm_answer)
    agent = ComplianceAgent()
    state = await agent.run(
        {
            "query": "请比较年假制度和差旅制度的区别",
            "rewritten_query": "请比较年假制度和差旅制度的区别",
            "current_user": object(),
            "search_type": "hybrid",
            "db": object(),
            "intent": "compare",
        }
    )

    assert "| 主题 | 文档A | 文档B | 差异说明 |" in state["answer"]
    assert "年假制度" in state["answer"]
    assert "差旅制度" in state["answer"]


def test_hybrid_searcher_includes_graph_for_compare_query():
    searcher = HybridSearcher()
    assert searcher._should_include_graph("请比较两版制度差异") is True
    assert searcher._should_include_graph("年假制度是什么") is False


def test_graph_searcher_infers_relationship():
    searcher = GraphSearcher()
    assert searcher._infer_relationship("谁负责审批", "该部门负责人审批") == "manages"
    assert searcher._infer_relationship("修订关系", "新制度替代旧制度") == "amends"
