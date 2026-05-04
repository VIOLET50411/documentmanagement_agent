"""Generator node: LLM-based RAG answer generation with deterministic fallback."""

from __future__ import annotations

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.generator")

GENERATION_SYSTEM_PROMPT = """你是企业文档智能问答助手 DocMind。你的回答风格应当专业、结构清晰、便于阅读。

## 回答要求

1. **结构化回答**：使用以下框架组织回答
   - 先给出简明直接的结论
   - 再用编号列表展开关键要点
   - 涉及流程的用步骤编号说明
   - 最后标注引用来源

2. **引用规范**：每个事实性陈述后标注 [来源: 文档标题]

3. **语言风格**：
   - 使用清晰、专业的简体中文
   - 善用 Markdown 格式（加粗、列表、分隔线）
   - 避免冗长，追求精炼

4. **诚实原则**：
   - 仅依据提供的文档证据回答
   - 证据不足时明确标注"⚠️ 当前知识库中暂无此项制度的完整规定"
   - 绝不编造不存在的制度或数据"""


async def generator(state: dict) -> dict:
    """Generate final answer from retrieved docs."""
    retrieved_docs = state.get("retrieved_docs") or []
    if state.get("answer"):
        return state

    if not retrieved_docs:
        state["answer"] = (
            "⚠️ **检索结果为空**\n\n"
            "当前知识库中未找到与您问题直接相关的文档内容。\n\n"
            "**建议**：\n"
            "1. 尝试更换关键词重新提问\n"
            "2. 联系管理员确认相关文档是否已上传至系统\n"
            "3. 如需了解特定制度，请提供更具体的制度名称"
        )
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
            # Build concise context — limit to 300 chars per doc to avoid
            # overwhelming small models with long context
            context_lines = []
            for idx, item in enumerate(retrieved_docs[:5], start=1):
                title = item.get("document_title") or "未知文档"
                section = item.get("section_title") or "未命名章节"
                page = item.get("page_number")
                snippet = (item.get("snippet") or "").strip()[:300]
                page_str = f" | 页码: {page}" if page else ""
                context_lines.append(
                    f"[证据{idx}] 《{title}》{section}{page_str}\n{snippet}"
                )

            query = state.get("rewritten_query") or state.get("query") or ""
            user_prompt = (
                f"## 用户问题\n{query}\n\n"
                f"## 文档证据\n" + "\n\n".join(context_lines) + "\n\n"
                f"## 请用结构化的中文回答上述问题，先给结论，再列要点，最后标注来源。"
            )
            answer = await llm.generate(
                system_prompt=GENERATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.15,
                max_tokens=1024,
            )
            if answer and len(answer.strip()) > 10 and _is_valid_chinese(answer):
                state["answer"] = answer.strip()
                state["generation_source"] = "llm"
                logger.info("generator.llm_ok", chars=len(state["answer"]))
                return state
            else:
                logger.warning("generator.llm_low_quality", answer_len=len(answer or ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("generator.llm_failed", error=str(exc))

    # Deterministic fallback: structured rule-based answer
    state["answer"] = _build_rule_fallback(state.get("query") or "", retrieved_docs)
    state["generation_source"] = "rule_fallback"
    return state


def _is_valid_chinese(text: str) -> bool:
    """Check if the output contains reasonable Chinese content (not garbled)."""
    if not text:
        return False
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # At least 10% of non-whitespace chars should be Chinese
    non_space = len(text.replace(" ", "").replace("\n", ""))
    if non_space == 0:
        return False
    return chinese_chars / non_space > 0.08


def _build_rule_fallback(query: str, retrieved_docs: list[dict]) -> str:
    """Build a well-structured deterministic answer from retrieved chunks."""
    lines = [
        f"## 关于「{query}」的检索结果\n",
        "> 以下内容基于知识库文档检索结果整理，供参考。\n",
    ]

    for index, item in enumerate(retrieved_docs[:3], start=1):
        title = item.get("document_title") or "未知文档"
        section = item.get("section_title") or "未命名章节"
        page = item.get("page_number")
        snippet = (item.get("snippet") or "").strip()[:200]

        source = f"《{title}》"
        if page:
            source += f" 第 {page} 页"
        source += f" / {section}"

        lines.append(f"### {index}. {source}\n")
        if snippet:
            lines.append(f"{snippet}\n")

    lines.append("---")
    lines.append("*如需更详细的解读，建议上传相关制度文件后重新提问。*")

    return "\n".join(lines)
