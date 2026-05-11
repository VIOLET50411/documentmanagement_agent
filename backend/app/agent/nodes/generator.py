"""Generator node: LLM-based RAG answer generation with deterministic fallback."""

from __future__ import annotations

import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.generator")

GENERATION_SYSTEM_PROMPT = """你是企业文档问答助手 DocMind。请严格基于给定证据，用简体中文输出清晰、可信、可核对的回答。

回答要求：
1. 先直接回答用户问题，再分点说明关键依据。
2. 只使用提供的文档证据，不要补充未出现的制度内容。
3. 涉及流程时，尽量按步骤说明。
4. 如果证据不足，要明确指出缺口，不要假装知道。
5. 不要在回答末尾单独输出“引用依据”“参考文档”或来源清单，来源会由前端单独展示。"""


async def generator(state: dict) -> dict:
    """Generate final answer from retrieved docs."""
    retrieved_docs = state.get("retrieved_docs") or []
    evidence_pack = state.get("evidence_pack") if isinstance(state.get("evidence_pack"), dict) else {}
    task_mode = str(state.get("task_mode") or "qa")
    if state.get("answer"):
        return state

    if not retrieved_docs:
        state["answer"] = (
            "## 未找到可用证据\n\n"
            "当前知识库中没有检索到与该问题直接相关的文档内容。\n\n"
            "你可以尝试：\n"
            "1. 换用更具体的关键词后重新提问。\n"
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
            context_lines = _build_llm_context_lines(retrieved_docs, evidence_pack)
            query = state.get("rewritten_query") or state.get("query") or ""
            conversation_state = state.get("conversation_state") if isinstance(state.get("conversation_state"), dict) else {}
            user_prompt = (
                f"## 用户问题\n{query}\n\n"
                f"## 任务模式\n{_describe_task_mode(task_mode)}\n\n"
                "## 对话上下文\n"
                f"主题：{conversation_state.get('subject') or '未识别'}\n"
                f"追问：{'是' if conversation_state.get('is_follow_up') else '否'}\n"
                f"版本：{conversation_state.get('version_scope') or '未指定'}\n\n"
                f"## 文档证据\n{chr(10).join(context_lines)}\n\n"
                f"## 输出要求\n{_prompt_for_task_mode(task_mode)}\n"
            )
            answer = await llm.generate(
                system_prompt=GENERATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.15,
                max_tokens=1024,
            )
            if answer and len(answer.strip()) > 10 and _is_valid_chinese(answer) and _passes_task_shape(answer, task_mode):
                state["answer"] = answer.strip()
                state["generation_source"] = "llm"
                logger.info("generator.llm_ok", chars=len(state["answer"]))
                return state
            logger.warning("generator.llm_low_quality", answer_len=len(answer or ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("generator.llm_failed", error=str(exc))

    state["answer"] = _build_rule_fallback(
        state.get("query") or "",
        retrieved_docs,
        task_mode=task_mode,
        evidence_pack=evidence_pack,
    )
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


def _passes_task_shape(answer: str, task_mode: str) -> bool:
    normalized = answer or ""
    if task_mode == "extract":
        return ("### 提取字段" in normalized or "### 关键信息字段" in normalized) and "所需材料" in normalized
    if task_mode == "process":
        return "### 关键步骤" in normalized or "### 关键步骤 / 证据" in normalized
    if task_mode == "summary":
        return "### 关键要点" in normalized
    return True


def _build_rule_fallback(
    query: str,
    retrieved_docs: list[dict],
    *,
    task_mode: str = "qa",
    evidence_pack: dict | None = None,
) -> str:
    """Build a structured deterministic answer from retrieved chunks."""
    evidence_blocks = []
    lead = ""
    pack = evidence_pack or {}
    salient_points = pack.get("salient_points") if isinstance(pack.get("salient_points"), list) else []

    base_items = salient_points[:3] if salient_points else retrieved_docs[:3]
    for item in base_items:
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

    if not evidence_blocks:
        return (
            f"## 关于“{query}”的回答\n\n"
            "当前检索链路已命中相关文档，但没有提取到足够可引用的正文片段，暂时无法形成可靠结论。\n\n"
            "建议重新提问，或上传包含具体制度条文、流程说明的文档后再试。"
        )

    answer_lines = [f"## 关于“{query}”的回答", ""]
    answer_lines.extend(_build_fallback_body(task_mode, lead, evidence_blocks))
    return "\n".join(answer_lines)


def _build_fallback_body(task_mode: str, lead: str, evidence_blocks: list[str]) -> list[str]:
    conclusion = lead or "当前已命中相关文档，但暂未提取到足够稳定的正文证据。"
    if task_mode == "process":
        return [
            f"**流程结论：** {conclusion}",
            "",
            "### 关键步骤 / 证据",
            "",
            *evidence_blocks,
            "",
            "### 提示",
            "- 若要进一步细化，可继续追问每一步的责任人、所需材料和例外情形。",
        ]
    if task_mode == "extract":
        extracted_fields = _extract_structured_fields(evidence_blocks)
        field_lines = extracted_fields or ["- 当前证据更偏原文段落，暂未稳定抽取出结构化字段。"]
        return [
            f"**提取结论：** {conclusion}",
            "",
            "### 提取字段",
            "",
            *field_lines,
            "",
            "### 关键依据",
            "",
            *evidence_blocks,
            "",
            "### 提示",
            "- 如需固定字段输出，可继续指定“材料、条件、金额、负责人、生效时间”等字段。",
        ]
    if task_mode == "draft":
        return [
            f"**起草依据：** {conclusion}",
            "",
            "### 可直接引用的证据",
            "",
            *evidence_blocks,
            "",
            "### 提示",
            "- 当前先给出起草依据；如需正式文稿，可继续说明用途、对象和语气。",
        ]
    return [
        f"**直接结论：** {conclusion}",
        "",
        "### 引用依据",
        "",
        *evidence_blocks,
        "",
        "### 说明",
        "- 上述内容为检索证据整理结果，优先保留原文含义，不额外补充未出现的制度细节。",
        "- 如需继续解释流程、角色分工或系统链路，可以继续追问具体环节。",
    ]


def _extract_structured_fields(evidence_blocks: list[str]) -> list[str]:
    text = "\n".join(evidence_blocks)
    fields: list[str] = []
    seen: set[str] = set()
    patterns = [
        ("所需材料", r"(聘用合同|社保缴纳证明|人事档案|岗位任务书|干部履历表|报到材料)"),
        ("办理条件", r"(应届毕业生|无工作经历|工作时间不满\s*1\s*年|连续\s*1\s*年及以上正式工作经历)"),
        ("时间要求", r"(入职后\s*\d+\s*个月内|当天|起始日期|截止日期|当月\s*15\s*日以前|当月\s*15\s*日以后)"),
    ]
    for label, pattern in patterns:
        matches = []
        for match in re.findall(pattern, text):
            value = " ".join(str(match).split()).strip("，。；; ")
            if value and value not in matches:
                matches.append(value)
        if matches:
            line = f"- {label}：{'、'.join(matches[:5])}"
            if line not in seen:
                seen.add(line)
                fields.append(line)
    return fields


def _build_llm_context_lines(retrieved_docs: list[dict], evidence_pack: dict) -> list[str]:
    lines = []
    salient_points = evidence_pack.get("salient_points") if isinstance(evidence_pack.get("salient_points"), list) else []
    source_items = salient_points[:6] if salient_points else retrieved_docs[:5]
    for idx, item in enumerate(source_items, start=1):
        title = item.get("document_title") or item.get("doc_title") or "未命名文档"
        section = item.get("section_title") or "未命名章节"
        page = item.get("page_number")
        snippet = (item.get("snippet") or "").strip()[:300]
        page_str = f" | 页码：{page}" if page else ""
        category = item.get("category")
        category_str = f" | 类别：{category}" if category else ""
        lines.append(f"[证据{idx}] 《{title}》 {section}{page_str}{category_str}\n{snippet}")
    return lines


def _describe_task_mode(task_mode: str) -> str:
    return {
        "qa": "问答",
        "summary": "摘要",
        "compare": "对比",
        "process": "流程说明",
        "extract": "字段提取",
        "draft": "起草辅助",
    }.get(task_mode, "问答")


def _prompt_for_task_mode(task_mode: str) -> str:
    prompts = {
        "process": "请先给出流程结论，再按步骤说明关键动作、责任环节和注意事项。",
        "extract": "请先给出提取结论，再分条列出关键字段、限制条件和缺失信息。",
        "draft": "请先概括可起草的核心结论，再列出可直接引用的依据和仍需补充的信息。",
        "compare": "请先给出对比结论，再列出主要差异点和适用建议。",
        "summary": "请先给出摘要结论，再列出 3 条关键要点。",
    }
    return prompts.get(task_mode, "请先给出直接结论，再分点说明关键依据、条件限制和必要边界。")


def _clean_snippet(snippet: str) -> str:
    snippet = re.sub(r"\s+", " ", snippet or "").strip()
    if not snippet:
        return ""
    snippet = snippet.replace("| --- |", "|")
    snippet = snippet.replace("```", "")
    return snippet[:220]
