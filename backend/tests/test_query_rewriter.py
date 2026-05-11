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
    assert state["conversation_state"]["subject"] == "2026 差旅报销制度"
    assert state["conversation_state"]["is_follow_up"] is True


@pytest.mark.asyncio
async def test_query_rewriter_passthroughs_non_ambiguous_query(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    state = await query_rewriter({"query": "差旅报销审批流程", "messages": []})

    assert state["rewrite_source"] == "passthrough"
    assert state["rewritten_query"] == "差旅报销审批流程"
    assert state["conversation_state"]["task_mode"] == "qa"


@pytest.mark.asyncio
async def test_query_rewriter_uses_previous_explicit_subject_for_version_follow_up(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    state = await query_rewriter(
        {
            "query": "和上一版有什么区别？",
            "messages": [
                {"role": "user", "content": "请说明《西南大学差旅报销制度（2024版）》的主要内容"},
                {"role": "assistant", "content": "已根据《西南大学差旅报销制度（2024版）》整理了要点。"},
            ],
        }
    )

    assert state["rewrite_source"] == "context_fallback"
    assert "《西南大学差旅报销制度（2024版）》" in state["rewritten_query"]
    assert "和上一版有什么区别？" in state["rewritten_query"]
    assert state["conversation_state"]["version_scope"] == "上一版"


@pytest.mark.asyncio
async def test_query_rewriter_rewrites_explicit_title_summary_query(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    state = await query_rewriter(
        {
            "query": "请说明《西南大学新进教职工合同签订常见问题》的主要内容",
            "messages": [],
            "task_mode": "summary",
        }
    )

    assert state["rewrite_source"] == "explicit_title"
    assert state["rewritten_query"] == "西南大学新进教职工合同签订常见问题 主要内容 要点"
    assert state["conversation_state"]["subject"] == "《西南大学新进教职工合同签订常见问题》"


@pytest.mark.asyncio
async def test_query_rewriter_uses_assistant_reference_titles_for_follow_up(monkeypatch):
    async def no_llm_generate(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", no_llm_generate)
    state = await query_rewriter(
        {
            "query": "那需要哪些材料？",
            "messages": [
                {"role": "user", "content": "请说明《西南大学国内差旅费管理办法（修订）》的主要内容"},
                {"role": "assistant", "content": "已整理主要内容。\n[参考文档: 西南大学国内差旅费管理办法（修订）]"},
            ],
        }
    )

    assert state["rewrite_source"] == "context_fallback"
    assert "西南大学国内差旅费管理办法（修订）" in state["rewritten_query"]
    assert "那需要哪些材料？" in state["rewritten_query"]


@pytest.mark.asyncio
async def test_query_rewriter_rejects_answer_shaped_llm_output(monkeypatch):
    async def bad_llm_generate(*args, **kwargs):
        return (
            "主要内容如下：\n"
            "1. 所需材料：身份证明。\n"
            "2. 办理条件：符合入职要求。"
        )

    monkeypatch.setattr("app.services.llm_service.LLMService.generate", bad_llm_generate)
    state = await query_rewriter(
        {
            "query": "那需要哪些材料？",
            "messages": [
                {"role": "user", "content": "请说明《西南大学新进教职工合同签订常见问题》的主要内容"},
                {"role": "assistant", "content": "已整理主要内容。\n[参考文档: 西南大学新进教职工合同签订常见问题]"},
            ],
            "task_mode": "extract",
        }
    )

    assert state["rewrite_source"] == "context_fallback"
    assert state["rewritten_query"] == "《西南大学新进教职工合同签订常见问题》 材料 要求；补充问题：那需要哪些材料？"
