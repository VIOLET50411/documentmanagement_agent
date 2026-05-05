"""Query rewriter with LLM rewrite and conversation fallback."""

from __future__ import annotations

import re

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

REWRITE_SYSTEM_PROMPT = """你是企业文档检索助手的查询改写器。请把用户问题改写成更适合制度文档检索的形式，并遵守以下规则：
1. 如果问题里有指代词，结合历史消息补全对象；
2. 保留核心意图，不要扩写成无关内容；
3. 优先补全制度名称、部门名称、主题词、版本或时间信息；
4. 只输出一条改写后的查询，不要附加解释。"""


async def query_rewriter(state: dict) -> dict:
    """Rewrite query for retrieval."""
    query = (state.get("query") or "").strip()
    messages = state.get("messages") or []

    context_messages = [msg for msg in messages if msg.get("role") == "user" and msg.get("content")]
    prior_user_messages = context_messages[:-1] if context_messages and context_messages[-1].get("content", "").strip() == query else context_messages
    has_ambiguous = any(ref in query for ref in AMBIGUOUS_REFERENCES)
    needs_rewrite = has_ambiguous or len(query) < 8 or len(prior_user_messages) > 0

    llm = LLMService()
    if not llm.is_rule_only and needs_rewrite:
        try:
            history_text = ""
            if prior_user_messages:
                recent = prior_user_messages[-3:]
                history_text = "\n".join(f"- {msg['content'].strip()[:120]}" for msg in recent)

            user_prompt = f"历史消息：\n{history_text}\n\n当前问题：{query}" if history_text else f"当前问题：{query}"
            result = await llm.generate(
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=150,
            )
            rewritten = _normalize_rewrite_result(result)
            if rewritten:
                if has_ambiguous and prior_user_messages:
                    previous = prior_user_messages[-1]["content"].strip()
                    if previous and previous not in rewritten:
                        rewritten = f"{previous}；补充问题：{query}"
                if len(rewritten) < 500:
                    state["rewritten_query"] = rewritten
                    state["rewrite_source"] = "llm"
                    logger.info("query_rewriter.llm", original=query[:60], rewritten=rewritten[:60])
                    return state
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("query_rewriter.llm_failed", error=str(exc))

    if has_ambiguous and prior_user_messages:
        previous = prior_user_messages[-1]["content"].strip()
        state["rewritten_query"] = f"{previous}；补充问题：{query}"
        state["rewrite_source"] = "context_fallback"
        return state

    state["rewritten_query"] = query
    state["rewrite_source"] = "passthrough"
    return state


def _normalize_rewrite_result(result: str | None) -> str | None:
    if not result:
        return None
    rewritten = result.strip().strip("\"").strip("'")
    if not rewritten:
        return None
    if "```" in rewritten:
        rewritten = rewritten.replace("```", "").strip()
    if not _looks_like_valid_rewrite(rewritten):
        return None
    return rewritten


def _looks_like_valid_rewrite(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 3:
        return False
    if stripped.count("?") >= 3 or "�" in stripped:
        return False
    if re.fullmatch(r"[\?\s]+", stripped):
        return False
    chinese_chars = sum(1 for c in stripped if "\u4e00" <= c <= "\u9fff")
    alnum_chars = sum(1 for c in stripped if c.isalnum())
    return chinese_chars > 0 or alnum_chars >= 6
