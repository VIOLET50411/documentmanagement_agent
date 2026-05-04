"""Query rewriter with LLM rewrite and conversation fallback."""

from __future__ import annotations

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.query_rewriter")

AMBIGUOUS_REFERENCES = (
    "这个",
    "这个制度",
    "这份",
    "这份制度",
    "该制度",
    "该规范",
    "它",
    "其",
    "this",
    "that",
    "it",
)

REWRITE_SYSTEM_PROMPT = """你是企业文档检索助手的查询改写器。请把用户问题改写成更适合企业文档检索的形式，并遵守以下规则：
1. 如果问题里有指代词，请结合历史消息补全对象。
2. 保留核心意图，不要扩写成无关内容。
3. 优先补全制度名、部门名、主题词、版本或时间信息。
4. 输出只包含一条改写后的查询，不要附加解释。"""


async def query_rewriter(state: dict) -> dict:
    """Rewrite query for retrieval."""
    query = (state.get("query") or "").strip()
    messages = state.get("messages") or []

    context_messages = [msg for msg in messages if msg.get("role") == "user" and msg.get("content")]
    has_ambiguous = any(ref in query for ref in AMBIGUOUS_REFERENCES)
    needs_rewrite = has_ambiguous or len(query) < 8 or len(context_messages) > 0

    llm = LLMService()
    if not llm.is_rule_only and needs_rewrite:
        try:
            history_text = ""
            if context_messages:
                recent = context_messages[-3:]
                history_text = "\n".join(f"- {msg['content'].strip()[:120]}" for msg in recent)

            user_prompt = f"历史消息：\n{history_text}\n\n当前问题：{query}" if history_text else f"当前问题：{query}"
            result = await llm.generate(
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=150,
            )
            if result and len(result.strip()) > 3:
                rewritten = result.strip().strip("\"").strip("'")
                if has_ambiguous and context_messages:
                    previous = context_messages[-1]["content"].strip()
                    if previous and previous not in rewritten:
                        rewritten = f"{previous}；补充问题：{query}"
                if len(rewritten) < 500:
                    state["rewritten_query"] = rewritten
                    state["rewrite_source"] = "llm"
                    logger.info("query_rewriter.llm", original=query[:60], rewritten=rewritten[:60])
                    return state
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("query_rewriter.llm_failed", error=str(exc))

    if has_ambiguous and context_messages:
        previous = context_messages[-1]["content"].strip()
        state["rewritten_query"] = f"{previous}；补充问题：{query}"
        state["rewrite_source"] = "context_fallback"
        return state

    state["rewritten_query"] = query
    state["rewrite_source"] = "passthrough"
    return state
