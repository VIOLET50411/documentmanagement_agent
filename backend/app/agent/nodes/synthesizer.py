"""合成器节点：合并多个子查询的检索结果生成最终回答。"""

from __future__ import annotations

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.synthesizer")

SYNTHESIS_SYSTEM_PROMPT = """你是企业文档问答助手 DocMind 的综合分析器。你需要将多个子查询的检索结果合并，生成专业、充实、结构化的综合分析回答。

要求：
1. 根据合成策略组织回答结构。
2. 每个分析点需有文档证据支持，避免空泛总结。
3. 对比分析时，必须明确列出各项的异同点。
4. 综合整理时，要找出共性和关联。
5. 分主题展开时，每个主题独立成段且信息完整。
6. 不要在回答末尾单独输出"引用依据""参考文档"或来源清单。
7. 确保回答完整、准确、逻辑清晰。
8. 使用通顺自然的中文表达。"""

# ── 策略 prompt 模板 ──
_STRATEGY_PROMPTS = {
    "compare": (
        "请按对比分析的形式组织回答：\n"
        "1. 先给出整体对比结论。\n"
        "2. 分维度列出各项的异同点（可用表格或分点）。\n"
        "3. 给出适用建议或总结。"
    ),
    "merge": (
        "请按综合整理的形式组织回答：\n"
        "1. 先给出综合结论。\n"
        "2. 分主题整理关键信息，找出共性和关联。\n"
        "3. 补充说明需要注意的边界条件。"
    ),
    "enumerate": (
        "请按分主题展开的形式组织回答：\n"
        "1. 每个主题独立成段，标题清晰。\n"
        "2. 每段给出该主题的核心要点和依据。\n"
        "3. 最后给出综合说明。"
    ),
}


def _build_synthesis_prompt(
    query: str,
    sub_results: list[dict],
    strategy: str,
) -> str:
    """构建合成器的用户 prompt。"""
    parts: list[str] = [f"## 原始查询\n{query}\n"]

    for idx, item in enumerate(sub_results, start=1):
        sub_query = item.get("sub_query", f"子查询{idx}")
        docs = item.get("retrieved_docs") or []
        parts.append(f"## 子查询 {idx}：{sub_query}")
        if docs:
            for doc_idx, doc in enumerate(docs[:4], start=1):
                title = doc.get("document_title") or "未命名文档"
                section = doc.get("section_title") or ""
                snippet = (doc.get("snippet") or "")[:400]
                page = doc.get("page_number")
                page_str = f" | 页码：{page}" if page else ""
                parts.append(
                    f"[证据{idx}-{doc_idx}] 《{title}》 {section}{page_str}\n{snippet}"
                )
        else:
            parts.append("（未检索到相关文档）")
        parts.append("")

    strategy_prompt = _STRATEGY_PROMPTS.get(strategy, _STRATEGY_PROMPTS["merge"])
    parts.append(f"## 合成要求\n{strategy_prompt}")

    return "\n".join(parts)


def _build_rule_fallback(
    query: str,
    sub_results: list[dict],
    strategy: str,
) -> str:
    """规则回退：无 LLM 时的结构化合成。"""
    lines: list[str] = [f"## 关于\u201c{query}\u201d的综合分析\n"]

    if strategy == "compare":
        lines.append("### 对比分析\n")
        for idx, item in enumerate(sub_results, start=1):
            sub_query = item.get("sub_query", f"子查询{idx}")
            docs = item.get("retrieved_docs") or []
            lines.append(f"**{sub_query}**\n")
            if docs:
                for doc in docs[:3]:
                    title = doc.get("document_title") or "未命名文档"
                    snippet = (doc.get("snippet") or "").strip()[:300]
                    if snippet:
                        lines.append(f"- {snippet} [《{title}》]")
            else:
                lines.append("- 未检索到相关内容。")
            lines.append("")

    elif strategy == "enumerate":
        for idx, item in enumerate(sub_results, start=1):
            sub_query = item.get("sub_query", f"子查询{idx}")
            docs = item.get("retrieved_docs") or []
            lines.append(f"### {idx}. {sub_query}\n")
            if docs:
                for doc in docs[:3]:
                    title = doc.get("document_title") or "未命名文档"
                    snippet = (doc.get("snippet") or "").strip()[:300]
                    if snippet:
                        lines.append(f"- {snippet} [《{title}》]")
            else:
                lines.append("- 未检索到相关内容。")
            lines.append("")

    else:  # merge
        lines.append("### 综合整理\n")
        all_snippets: list[str] = []
        for item in sub_results:
            docs = item.get("retrieved_docs") or []
            for doc in docs[:3]:
                title = doc.get("document_title") or "未命名文档"
                snippet = (doc.get("snippet") or "").strip()[:300]
                if snippet:
                    all_snippets.append(f"- {snippet} [《{title}》]")
        if all_snippets:
            lines.extend(all_snippets[:8])
        else:
            lines.append("- 未检索到足够的相关内容。")
        lines.append("")

    lines.append("### 说明")
    lines.append("- 上述内容为多维度检索结果的结构化整理，优先保留原文信息。")
    lines.append("- 如需深入分析，可针对具体方面继续追问。")

    return "\n".join(lines)


def _merge_citations(sub_results: list[dict]) -> list[dict]:
    """合并所有子查询的检索结果为统一的引用列表。"""
    citations: list[dict] = []
    seen: set[str] = set()
    for item in sub_results:
        docs = item.get("retrieved_docs") or []
        for doc in docs[:4]:
            doc_id = str(doc.get("doc_id") or "")
            section = str(doc.get("section_title") or "")
            key = f"{doc_id}:{section}"
            if key in seen:
                continue
            seen.add(key)
            citations.append({
                "doc_id": doc.get("doc_id"),
                "doc_title": doc.get("document_title") or "未命名文档",
                "page_number": doc.get("page_number"),
                "section_title": doc.get("section_title"),
                "snippet": doc.get("snippet", ""),
                "relevance_score": doc.get("score", 0.0),
            })
    return citations[:10]


async def synthesizer(state: dict) -> dict:
    """合成器节点：合并多个子查询的检索结果生成最终回答。"""
    sub_results = state.get("sub_results") or []
    strategy = state.get("synthesis_strategy") or "merge"
    query = state.get("rewritten_query") or state.get("query") or ""

    if not sub_results:
        state["answer"] = "未能获取子查询的检索结果，无法生成综合分析。"
        state["synthesis_source"] = "empty"
        return state

    # 合并引用
    state["citations"] = _merge_citations(sub_results)

    # 合并所有检索文档到 retrieved_docs
    all_docs: list[dict] = []
    for item in sub_results:
        all_docs.extend(item.get("retrieved_docs") or [])
    state["retrieved_docs"] = all_docs[:12]

    # 尝试 LLM 合成
    llm = LLMService()
    if not llm.is_rule_only:
        try:
            user_prompt = _build_synthesis_prompt(query, sub_results, strategy)
            answer = await llm.generate(
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            if answer and len(answer.strip()) > 20:
                state["answer"] = answer.strip()
                state["synthesis_source"] = "llm"
                state["selected_agent"] = "synthesizer"
                logger.info("synthesizer.llm_ok", chars=len(state["answer"]), strategy=strategy)
                return state
            logger.warning("synthesizer.llm_low_quality", answer_len=len(answer or ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("synthesizer.llm_failed", error=str(exc))

    # 规则回退
    state["answer"] = _build_rule_fallback(query, sub_results, strategy)
    state["synthesis_source"] = "rule_fallback"
    state["selected_agent"] = "synthesizer"
    return state
