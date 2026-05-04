import pytest

from app.agent.nodes.query_rewriter import query_rewriter


@pytest.mark.asyncio
async def test_query_rewriter_falls_back_to_context_for_chinese_ambiguous_reference(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    state = await query_rewriter(
        {
            "query": "这个什么时候生效？",
            "messages": [{"role": "user", "content": "2026 差旅报销制度"}],
        }
    )

    assert state["rewrite_source"] == "context_fallback"
    assert state["rewritten_query"] == "2026 差旅报销制度；补充问题：这个什么时候生效？"


@pytest.mark.asyncio
async def test_query_rewriter_passthroughs_non_ambiguous_query(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    state = await query_rewriter({"query": "差旅报销审批流程", "messages": []})

    assert state["rewrite_source"] == "passthrough"
    assert state["rewritten_query"] == "差旅报销审批流程"
