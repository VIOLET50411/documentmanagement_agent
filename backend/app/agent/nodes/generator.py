"""Generator node: LLM-based RAG answer generation with deterministic fallback."""

from __future__ import annotations

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.generator")

GENERATION_SYSTEM_PROMPT = """你是企业文档问答助手。请严格依据提供的文档证据回答用户问题。
规则：
1. 只能使用给出的证据，不得编造；
2. 先给结论，再给依据要点；
3. 如果证据不足，必须明确说明“证据不足”；
4. 使用清晰、专业的简体中文。"""


async def generator(state: dict) -> dict:
    """Generate final answer from retrieved docs."""
    retrieved_docs = state.get("retrieved_docs") or []
    if state.get("answer"):
        return state

    if not retrieved_docs:
        state["answer"] = "当前未检索到足够上下文，暂时无法生成回答。"
        state["citations"] = []
        return state

    citations = []
    for item in retrieved_docs[:5]:
        title = item.get("document_title") or "未知文档"
        section = item.get("section_title") or "未命名章节"
        citations.append(
            {
                "doc_id": item.get("doc_id"),
                "doc_title": title,
                "page_number": item.get("page_number"),
                "section_title": section,
                "snippet": item.get("snippet", ""),
                "relevance_score": item.get("score", 0.0),
            }
        )
    state["citations"] = citations

    llm = LLMService()
    if not llm.is_rule_only:
        try:
            context_lines = []
            for idx, item in enumerate(retrieved_docs[:5], start=1):
                title = item.get("document_title") or "未知文档"
                section = item.get("section_title") or "未命名章节"
                page = item.get("page_number")
                snippet = (item.get("snippet") or "").strip()[:500]
                context_lines.append(
                    f"[{idx}] 标题: {title} | 章节: {section} | 页码: {page}\n内容: {snippet}"
                )

            query = state.get("rewritten_query") or state.get("query") or ""
            user_prompt = f"用户问题：{query}\n\n可用文档证据：\n" + "\n\n".join(context_lines)
            answer = await llm.generate(
                system_prompt=GENERATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.15,
                max_tokens=800,
            )
            if answer and len(answer.strip()) > 10:
                state["answer"] = answer.strip()
                state["generation_source"] = "llm"
                logger.info("generator.llm_ok", chars=len(state["answer"]))
                return state
        except Exception as exc:  # noqa: BLE001
            logger.warning("generator.llm_failed", error=str(exc))

    top = retrieved_docs[0]
    lines = [
        "结论：当前为规则模式生成，以下内容基于检索结果直接整理。",
        "",
        f"核心片段：{(top.get('snippet') or '').strip()[:180]}",
        "",
        "引用：",
    ]
    for index, item in enumerate(retrieved_docs[:3], start=1):
        title = item.get("document_title") or "未知文档"
        section = item.get("section_title") or "未命名章节"
        page = item.get("page_number")
        source = f"《{title}》 / {section}" if page is None else f"《{title}》 第 {page} 页 / {section}"
        lines.append(f"{index}. {source}")

    state["answer"] = "\n".join(lines)
    state["generation_source"] = "rule_fallback"
    return state
