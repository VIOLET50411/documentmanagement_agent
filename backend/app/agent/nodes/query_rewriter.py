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

FOLLOW_UP_HINTS = (
    "什么时候",
    "何时",
    "多久",
    "哪些",
    "哪几",
    "怎么",
    "如何",
    "流程",
    "步骤",
    "材料",
    "条件",
    "范围",
    "区别",
    "差异",
    "依据",
    "负责",
    "审批",
    "版本",
    "生效",
    "适用",
)

VERSION_FOLLOW_UP_HINTS = (
    "上一版",
    "前一版",
    "旧版",
    "新版",
    "这一版",
    "这版",
    "前后版本",
    "和上一版",
    "与上一版",
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

    context_messages = [msg for msg in messages if msg.get("content")]
    user_messages = [msg for msg in context_messages if msg.get("role") == "user"]
    prior_user_messages = user_messages[:-1] if user_messages and user_messages[-1].get("content", "").strip() == query else user_messages
    has_ambiguous = any(ref in query for ref in AMBIGUOUS_REFERENCES)
    is_follow_up = _looks_like_follow_up(query)
    context_subject = _resolve_context_subject(context_messages, prior_user_messages)
    has_version_follow_up = any(token in query for token in VERSION_FOLLOW_UP_HINTS)
    needs_rewrite = (
        has_ambiguous
        or is_follow_up
        or has_version_follow_up
        or len(query) < 8
        or (bool(context_subject) and len(query) < 24)
    )

    llm = LLMService()
    if not llm.is_rule_only and needs_rewrite:
        try:
            history_text = ""
            if context_messages:
                recent = context_messages[-4:]
                history_text = "\n".join(
                    f"- {msg.get('role', 'user')}: {msg['content'].strip()[:120]}"
                    for msg in recent
                )

            user_prompt = f"历史消息：\n{history_text}\n\n当前问题：{query}" if history_text else f"当前问题：{query}"
            result = await llm.generate(
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=150,
            )
            rewritten = _normalize_rewrite_result(result)
            if rewritten:
                rewritten = _attach_context_subject(
                    rewritten,
                    query,
                    context_subject,
                    has_ambiguous=has_ambiguous,
                    is_follow_up=is_follow_up or has_version_follow_up,
                )
                if len(rewritten) < 500:
                    state["rewritten_query"] = rewritten
                    state["rewrite_source"] = "llm"
                    logger.info("query_rewriter.llm", original=query[:60], rewritten=rewritten[:60])
                    return state
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("query_rewriter.llm_failed", error=str(exc))

    if context_subject and (has_ambiguous or is_follow_up or has_version_follow_up):
        state["rewritten_query"] = _merge_subject_and_query(context_subject, query)
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


def _looks_like_follow_up(query: str) -> bool:
    stripped = query.strip()
    if not stripped:
        return False
    if any(token in stripped for token in FOLLOW_UP_HINTS):
        return True
    if len(stripped) <= 16 and stripped.endswith(("?", "？")):
        return True
    return False


def _resolve_context_subject(messages: list[dict], prior_user_messages: list[dict]) -> str:
    titles = []
    for msg in reversed(messages[-6:]):
        if msg.get("role") != "assistant":
            continue
        titles.extend(_extract_document_titles(msg.get("content", "")))
        if titles:
            break
    if titles:
        return "、".join(titles[:2])
    for msg in reversed(prior_user_messages[-4:]):
        subject = _extract_subject_from_user_query(msg.get("content", ""))
        if subject:
            return subject
    if prior_user_messages:
        return _compact_subject(prior_user_messages[-1].get("content", ""))
    return ""


def _extract_document_titles(text: str) -> list[str]:
    seen = set()
    titles = []
    for match in re.findall(r"《([^》]{2,60})》", text or ""):
        title = match.strip()
        if title and title not in seen:
            seen.add(title)
            titles.append(f"《{title}》")
    return titles


def _compact_subject(text: str) -> str:
    subject = re.split(r"[。！？\n；]", (text or "").strip(), maxsplit=1)[0].strip()
    if len(subject) > 60:
        subject = subject[:60].rstrip()
    return subject


def _extract_subject_from_user_query(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    explicit_titles = _extract_document_titles(raw)
    if explicit_titles:
        return explicit_titles[-1]

    subject_match = re.search(
        r"((?:\d{4}\s*)?[\u4e00-\u9fffA-Za-z0-9（）()《》]{2,40}(?:制度|办法|规定|流程|手册|规范|预算|合同|审批单|报销制度|报销办法))",
        raw,
    )
    if subject_match:
        return subject_match.group(1).strip("：:，,。；; ")

    return _compact_subject(raw)


def _attach_context_subject(rewritten: str, query: str, context_subject: str, *, has_ambiguous: bool, is_follow_up: bool) -> str:
    if not context_subject:
        return rewritten
    if context_subject in rewritten:
        return rewritten
    if has_ambiguous or is_follow_up:
        return _merge_subject_and_query(context_subject, query)
    return rewritten


def _merge_subject_and_query(subject: str, query: str) -> str:
    clean_subject = (subject or "").strip()
    clean_query = (query or "").strip()
    if not clean_subject:
        return clean_query
    if clean_subject in clean_query:
        return clean_query
    return f"{clean_subject}；补充问题：{clean_query}"
