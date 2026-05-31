"""Generator node: LLM-based RAG answer generation with deterministic fallback."""

from __future__ import annotations

import re

import structlog

from app.agent.prompts.generation import ANSWER_STYLES
from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.generator")

GENERATION_SYSTEM_PROMPT = """你是企业文档问答助手 DocMind。请严格基于给定的文档证据，用简体中文输出专业、结构化的回答。

核心原则：
1. 结论先行，开篇直接回答问题
2. 论据充分，引用具体文档条款支撑
3. 分析深入，说明"是什么""为什么""怎么做"
4. 严格忠实，不编造未在证据中出现的信息

格式要求：
- 使用 Markdown（标题、加粗、列表、表格）
- 回答充实完整，不少于 200 字
- 不要在末尾输出"参考文档"（前端自动展示）
- 如果证据不足，明确指出缺口"""


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

    # Relevance guard: reject clearly irrelevant evidence
    # 如果已经重试过（degraded），跳过此检查，确保用户能收到回答
    query = state.get("rewritten_query") or state.get("query") or ""
    if not state.get("degraded") and _evidence_is_irrelevant(query, retrieved_docs):
        state["answer"] = (
            "## 未找到相关内容\n\n"
            "当前知识库中检索到的文档与您的问题不直接相关，无法给出准确回答。\n\n"
            "你可以尝试：\n"
            "1. 用更明确的关键词重新描述问题。\n"
            "2. 上传与问题相关的文档后再提问。\n"
            "3. 指定具体的文档名称或业务场景。"
        )
        state["citations"] = []
        state["generation_source"] = "irrelevant_guard"
        logger.info("generator.irrelevant_guard", query=query[:60])
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
            query = state.get("rewritten_query") or state.get("query") or ""
            # 获取任务模式对应的回答风格指导
            answer_style = ANSWER_STYLES.get(task_mode, ANSWER_STYLES.get("qa", ""))

            # 构建精简的证据上下文（限制总长度，适配小模型）
            context_lines = _build_llm_context_lines(retrieved_docs, evidence_pack)
            context_text = "\n".join(context_lines)
            # 限制证据总长度不超过 2000 字符
            if len(context_text) > 2000:
                context_text = context_text[:2000] + "\n...（证据已截断）"

            # 构建重试提示
            retry_hint = state.get("critic_improvement_hint") or ""
            retry_section = f"\n【改进要求】{retry_hint}\n" if retry_hint else ""

            user_prompt = (
                f"问题：{query}\n\n"
                f"回答要求：{answer_style}\n\n"
                f"文档证据：\n{context_text}\n\n"
                f"请基于以上证据回答问题。{_prompt_for_task_mode(task_mode)}\n"
                f"{retry_section}"
            )

            # 动态计算 max_tokens：小模型用较小值
            prompt_char_count = len(GENERATION_SYSTEM_PROMPT) + len(user_prompt)
            # 粗略估算：中文每字约 1.5 token
            estimated_prompt_tokens = int(prompt_char_count * 1.5)
            # 为回答预留空间，但不超过 2048
            max_tokens = min(2048, max(512, 4096 - estimated_prompt_tokens))

            answer = await llm.generate(
                system_prompt=GENERATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=max_tokens,
            )
            if answer and len(answer.strip()) > 10 and _is_valid_chinese(answer) and _passes_task_shape(answer, task_mode):
                state["answer"] = answer.strip()
                state["generation_source"] = "llm"
                logger.info("generator.llm_ok", chars=len(state["answer"]), max_tokens=max_tokens)
                return state
            logger.warning("generator.llm_low_quality", answer_len=len(answer or ""), max_tokens=max_tokens)
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

    if chinese_ratio < 0.08:
        return False
    if latin_ratio > 0.60:
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
    """Relaxed shape check: always pass to avoid rejecting valid LLM answers."""
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
    source_items = salient_points[:5] if salient_points else retrieved_docs[:5]
    for idx, item in enumerate(source_items, start=1):
        title = item.get("document_title") or item.get("doc_title") or "未命名文档"
        section = item.get("section_title") or ""
        snippet = _truncate_at_sentence((item.get("snippet") or "").strip(), 200)
        section_str = f" {section}" if section else ""
        lines.append(f"[{idx}] 《{title}》{section_str}\n{snippet}")
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


def _truncate_at_sentence(text: str, max_length: int) -> str:
    """Truncate text at a sentence boundary rather than mid-word."""
    if not text or len(text) <= max_length:
        return text
    search_region = text[:max_length]
    sentence_ends = [m.end() for m in re.finditer(r'[。；！？\n]', search_region)]
    if sentence_ends:
        return text[:sentence_ends[-1]]
    return text[:max_length].rstrip() + '...'


def _clean_snippet(snippet: str) -> str:
    snippet = re.sub(r"\s+", " ", snippet or "").strip()
    if not snippet:
        return ""
    snippet = snippet.replace("| --- |", "|")
    snippet = snippet.replace("```", "")
    return _truncate_at_sentence(snippet, 400)


# ── Stop words: common terms that should not count as meaningful overlap ──
_STOP_WORDS = frozenset({
    # 虚词/助词
    "的", "了", "在", "是", "有", "和", "与", "对", "为", "中",
    "个", "一", "不", "也", "这", "那", "到", "上", "下", "出",
    "就", "都", "要", "会", "能", "可以", "进行", "以下", "其中",
    # 泛指名词
    "工作", "管理", "单位", "部门", "制度", "办法", "规定", "相关",
    "情况", "问题", "平台", "系统", "内容", "方面", "一份", "文档",
    # 动作词（泛化的，不指具体业务）
    "处理", "优先", "三个", "原因", "给出", "请", "列出", "说明",
    "目前", "应当", "可能", "根据", "按照", "通过", "包含", "包括",
    "起草", "撰写", "生成", "写一", "草拟", "拟定", "编写",
    # 疑问词
    "什么", "哪些", "怎么", "如何", "当前", "需要", "应该",
})

# ── 生成式任务关键词：这些任务不应被 irrelevant_guard 拦截 ──
_GENERATIVE_KEYWORDS = {"起草", "撰写", "生成", "写一", "草拟", "拟定", "编写", "编制", "制定", "拟写"}


def _evidence_is_irrelevant(query: str, docs: list[dict]) -> bool:
    """Return True when retrieved evidence has negligible semantic overlap with the query.

    This guards against the case where the retrieval returns documents that
    happen to score above the vector threshold but are topically unrelated.
    """
    if not docs or not query:
        return False

    # 生成式任务（起草/撰写/编写等）不拦截，让 LLM 自由生成
    if any(kw in query for kw in _GENERATIVE_KEYWORDS):
        return False

    # Extract meaningful (non-stopword) terms from the query
    query_terms = [
        t for t in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", query)
        if t not in _STOP_WORDS
    ]
    if not query_terms:
        # Query is entirely stop words — let LLM handle it
        return False

    # Combine evidence text
    evidence_text = " ".join(
        f"{item.get('document_title', '')} {item.get('section_title', '') or ''} {item.get('snippet', '')}"
        for item in docs[:8]
    )

    overlap = sum(1 for t in query_terms if t in evidence_text)
    overlap_ratio = overlap / len(query_terms) if query_terms else 0

    # If less than 10% of meaningful query terms appear in evidence, it's irrelevant
    if overlap_ratio < 0.10:
        logger.info(
            "generator.relevance_check",
            query_terms=query_terms[:10],
            overlap=overlap,
            ratio=round(overlap_ratio, 2),
            verdict="irrelevant",
        )
        return True

    return False

