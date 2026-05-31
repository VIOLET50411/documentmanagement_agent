"""指代消解节点：检测并替换查询中的指代词为具体实体名。"""

from __future__ import annotations

import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.coreference_resolver")

COREFERENCE_SYSTEM_PROMPT = """你是企业文档问答系统的指代消解器。你的任务是把用户查询中的指代词替换为对应的具体实体名称。

规则：
1. 仅替换指代词，保留原始问题结构和意图。
2. 根据对话历史和上下文主题确定指代对象。
3. 如果指代对象不明确，保持原文不变。
4. 只输出消解后的查询文本，不要附加解释。
5. 不要改写、扩展或合并问题内容，仅做指代替换。"""

# ── 指代词正则模式 ──
_REFERENCE_PATTERNS = [
    re.compile(r"上面那个"),
    re.compile(r"上面的"),
    re.compile(r"这个制度"),
    re.compile(r"这个规范"),
    re.compile(r"这个办法"),
    re.compile(r"这份制度"),
    re.compile(r"这份文件"),
    re.compile(r"这份"),
    re.compile(r"这个"),
    re.compile(r"该制度"),
    re.compile(r"该规范"),
    re.compile(r"该办法"),
    re.compile(r"该文件"),
    re.compile(r"那个制度"),
    re.compile(r"那个"),
    re.compile(r"(?<![a-zA-Z])它(?![们])"),
    re.compile(r"其中"),
    re.compile(r"第[一二三四五六七八九十\d]+条"),
    re.compile(r"前面提到的"),
    re.compile(r"刚才说的"),
    re.compile(r"上面说的"),
    re.compile(r"上述"),
]


def _has_reference(query: str) -> bool:
    """检测查询中是否包含指代词。"""
    return any(pattern.search(query) for pattern in _REFERENCE_PATTERNS)


def _build_context_text(messages: list[dict], conversation_state: dict) -> str:
    """用最近 3 轮对话 + conversation_state 构建上下文文本。"""
    parts: list[str] = []

    # 最近 3 轮对话
    recent = [msg for msg in messages if msg.get("content")][-6:]  # 3 轮 = 6 条消息
    for msg in recent:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()[:150]
        parts.append(f"- {role}: {content}")

    # conversation_state 中的主题信息
    subject = str(conversation_state.get("subject") or "").strip()
    if subject:
        parts.append(f"- 当前主题：{subject}")

    explicit_titles = conversation_state.get("explicit_titles")
    if isinstance(explicit_titles, list) and explicit_titles:
        parts.append(f"- 涉及文档：{'、'.join(explicit_titles[:3])}")

    return "\n".join(parts)


def _rule_based_resolve(query: str, subject: str) -> str:
    """规则回退：用 conversation_state.subject 替换常见指代词。"""
    if not subject:
        return query

    resolved = query
    # 按长度降序替换，避免短模式先匹配导致残留
    replacements = [
        ("上面那个", subject),
        ("上面的", subject),
        ("这个制度", subject),
        ("这个规范", subject),
        ("这个办法", subject),
        ("这份制度", subject),
        ("这份文件", subject),
        ("这份", subject),
        ("该制度", subject),
        ("该规范", subject),
        ("该办法", subject),
        ("该文件", subject),
        ("那个制度", subject),
        ("那个", subject),
        ("前面提到的", subject),
        ("刚才说的", subject),
        ("上面说的", subject),
        ("上述", subject),
        ("这个", subject),
    ]
    for ref, replacement in replacements:
        if ref in resolved:
            resolved = resolved.replace(ref, replacement, 1)
            break  # 只替换第一个匹配的指代词

    return resolved


async def coreference_resolver(state: dict) -> dict:
    """指代消解节点：检测并替换查询中的指代词。

    修改 state['query']，不修改 rewritten_query（那是 query_rewriter 的职责）。
    """
    query = (state.get("query") or "").strip()
    messages = state.get("messages") or []
    conversation_state = state.get("conversation_state") if isinstance(state.get("conversation_state"), dict) else {}

    # 无指代词则跳过
    if not _has_reference(query):
        state["coreference_resolved"] = False
        return state

    # 无历史消息且无上下文主题则跳过
    subject = str(conversation_state.get("subject") or "").strip()
    if not messages and not subject:
        state["coreference_resolved"] = False
        return state

    # 尝试 LLM 消解
    llm = LLMService()
    if not llm.is_rule_only:
        try:
            context_text = _build_context_text(messages, conversation_state)
            user_prompt = (
                f"对话上下文：\n{context_text}\n\n"
                f"当前查询：{query}\n\n"
                "请将查询中的指代词替换为具体实体名，只输出替换后的查询。"
            )
            result = await llm.generate(
                system_prompt=COREFERENCE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.05,
                max_tokens=256,
            )
            if result:
                resolved = result.strip().strip('"').strip("'")
                # 基本验证：结果不为空、长度合理、不是纯解释文本
                if (
                    resolved
                    and 2 < len(resolved) < 500
                    and not resolved.startswith(("好的", "以下", "解释"))
                    and "\n" not in resolved
                ):
                    state["query"] = resolved
                    state["coreference_resolved"] = True
                    state["coreference_source"] = "llm"
                    logger.info(
                        "coreference_resolver.llm",
                        original=query[:60],
                        resolved=resolved[:60],
                    )
                    return state
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("coreference_resolver.llm_failed", error=str(exc))

    # 规则回退
    if subject:
        resolved = _rule_based_resolve(query, subject)
        if resolved != query:
            state["query"] = resolved
            state["coreference_resolved"] = True
            state["coreference_source"] = "rule_fallback"
            logger.info(
                "coreference_resolver.rule_fallback",
                original=query[:60],
                resolved=resolved[:60],
            )
            return state

    state["coreference_resolved"] = False
    return state
