"""Generator node: LLM-based RAG answer generation with deterministic fallback."""

from __future__ import annotations

import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.generator")

GENERATION_SYSTEM_PROMPT = """你是企业文档智能问答助手 DocMind。请基于给定证据，用简体中文给出清晰、可靠、可核对的回答。

回答要求：
1. 先直接回答用户问题，再分点说明关键依据。
2. 只使用提供的文档证据，不要补充臆测内容。
3. 涉及流程时，尽量按步骤说明。
4. 如果证据不足，要明确指出缺口，不要假装知道。
5. 请勿在回答末尾单独列出“引用依据”、“参考文档”或任何来源列表，来源会在前端自动展示。
"""


async def generator(state: dict) -> dict:
    """Generate final answer from retrieved docs."""
    retrieved_docs = state.get("retrieved_docs") or []
    if state.get("answer"):
        return state

    if not retrieved_docs:
        state["answer"] = (
            "## 未找到可用证据\n\n"
            "当前知识库中没有检索到与该问题直接相关的文档内容。\n\n"
            "你可以尝试：\n"
            "1. 更换更具体的关键词后重新提问。\n"
            "2. 先上传相关制度、流程或说明文档。\n"
            "3. 指定文档名称、部门名称或业务场景后再问。"
        )
        state["citations"] = []
        state["generation_source"] = "empty"
        return state

    citations = []
    for item in retrieved_docs[:5]:
        title = item.get("document_title") or "未命名文档"
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
                title = item.get("document_title") or "未命名文档"
                section = item.get("section_title") or "未命名章节"
                page = item.get("page_number")
                snippet = (item.get("snippet") or "").strip()[:300]
                page_str = f" | 页码：{page}" if page else ""
                context_lines.append(f"[证据{idx}] 《{title}》 / {section}{page_str}\n{snippet}")

            query = state.get("rewritten_query") or state.get("query") or ""
            user_prompt = (
                f"## 用户问题\n{query}\n\n"
                f"## 文档证据\n{chr(10).join(chr(10) + line for line in context_lines).strip()}\n\n"
                "请输出结构化中文回答，格式建议为：\n"
                "1. 直接结论\n"
                "2. 关键说明\n"
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
            logger.warning("generator.llm_low_quality", answer_len=len(answer or ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("generator.llm_failed", error=str(exc))

    state["answer"] = _build_rule_fallback(state.get("query") or "", retrieved_docs)
    state["generation_source"] = "rule_fallback"
    return state


def _is_valid_chinese(text: str) -> bool:
    """Check if the output contains reasonable Chinese content."""
    if not text or len(text.strip()) < 20:
        return False

    cleaned = text.replace(" ", "").replace("\n", "").replace("\r", "")
    total = len(cleaned)
    if total == 0:
        return False

    chinese_chars = sum(1 for c in cleaned if "\u4e00" <= c <= "\u9fff")
    latin_chars = sum(1 for c in cleaned if ("a" <= c <= "z") or ("A" <= c <= "Z"))

    chinese_ratio = chinese_chars / total
    latin_ratio = latin_chars / total

    if chinese_ratio < 0.15:
        return False
    if latin_ratio > 0.40:
        return False

    code_patterns = [
        "()",
        "{}",
        "[];",
        "});",
        "def ",
        "import ",
        "class ",
        "function ",
        "async ",
        "await ",
        "return ",
        "=> ",
        "\\n\\n",
        "</",
        "/>",
        "console.",
        "print(",
        "self.",
        "None",
        "True",
        "False",
        "getElementById",
        "querySelector",
        "addEventListener",
        "httpx",
        "asyncio",
        "from ",
    ]
    if sum(1 for pattern in code_patterns if pattern in text) >= 3:
        return False

    script_flags = set()
    for c in cleaned[:500]:
        cp = ord(c)
        if 0x0400 <= cp <= 0x04FF:
            script_flags.add("cyrillic")
        elif 0x0E00 <= cp <= 0x0E7F:
            script_flags.add("thai")
        elif 0x0600 <= cp <= 0x06FF:
            script_flags.add("arabic")
        elif 0xAC00 <= cp <= 0xD7AF:
            script_flags.add("korean")
        elif 0x3040 <= cp <= 0x30FF:
            script_flags.add("japanese")
        elif 0x0370 <= cp <= 0x03FF:
            script_flags.add("greek")
    if len(script_flags) >= 2:
        return False

    words = text.split()
    if len(words) > 20:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len < 4.0 and latin_ratio > 0.25:
            return False

    return True


def _build_rule_fallback(query: str, retrieved_docs: list[dict]) -> str:
    """Build a structured deterministic answer from retrieved chunks."""
    evidence_blocks = []
    source_lines = []
    lead = ""

    for item in retrieved_docs[:3]:
        title = item.get("document_title") or item.get("doc_title") or "未命名文档"
        section = item.get("section_title") or "未命名章节"
        page = item.get("page_number")
        snippet = _clean_snippet(item.get("snippet") or "")
        source_label = f"《{title}》"
        if page:
            source_label += f" / 第 {page} 页"
        if section:
            source_label += f" / {section}"

        if snippet:
            evidence_blocks.append(f"- {snippet} [{source_label}]")
            if not lead:
                lead = snippet
        source_lines.append(f"- {source_label}")

    if not evidence_blocks:
        return (
            f"## 关于“{query}”的回答\n\n"
            "当前检索链路已命中相关文档，但没有提取到足够可引用的正文片段，暂时无法形成可靠结论。\n\n"
            "建议重新提问，或上传包含具体制度条文、流程说明的文档后再试。"
        )

    answer_lines = [
        f"## 关于“{query}”的回答",
        "",
        f"**直接结论：** {lead or '当前已命中相关文档，但暂未提取到足够稳定的正文证据。'}",
        "",
        "### 引用依据",
        "",
        *evidence_blocks,
        "",
        "### 说明",
        "- 上述内容为检索证据整理结果，优先保留原文含义，不额外补充未出现的制度细节。",
        "- 如果你希望我进一步解释流程、角色分工或系统链路，可以继续追问具体环节。",
    ]
    return "\n".join(answer_lines)


def _clean_snippet(snippet: str) -> str:
    snippet = re.sub(r"\s+", " ", snippet or "").strip()
    if not snippet:
        return ""
    snippet = snippet.replace("| --- |", "|")
    snippet = snippet.replace("```", "")
    return snippet[:220]
