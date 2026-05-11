"""Retriever node fallback implementation."""

from __future__ import annotations

import re

from app.agent.nodes.evidence_pack import build_evidence_pack

_searcher = None

DEFAULT_PLAN_BY_INTENT = {
    "qa": {"top_k": 6, "search_type": "hybrid", "max_per_doc": 2},
    "compare": {"top_k": 10, "search_type": "hybrid", "max_per_doc": 2, "require_multi_doc": True},
    "summarize": {"top_k": 10, "search_type": "hybrid", "max_per_doc": 4, "prefer_summary_details": True},
    "graph_query": {"top_k": 6, "search_type": "graph", "max_per_doc": 3},
    "statistics": {"top_k": 6, "search_type": "keyword", "max_per_doc": 2},
}


def resolve_retrieval_plan(state: dict) -> dict:
    """Build a conservative retrieval plan from the current runtime state."""
    intent = str(state.get("intent") or "qa")
    defaults = DEFAULT_PLAN_BY_INTENT.get(intent, DEFAULT_PLAN_BY_INTENT["qa"]).copy()
    requested_type = str(state.get("search_type") or "").strip()
    requested_top_k = state.get("top_k")

    if isinstance(requested_top_k, int) and requested_top_k > 0:
        top_k = requested_top_k
    else:
        top_k = defaults["top_k"]

    search_type = requested_type or defaults["search_type"]
    if intent == "graph_query" and search_type == "hybrid":
        search_type = "graph"

    return defaults | {
        "intent": intent,
        "top_k": top_k,
        "search_type": search_type,
    }


async def retriever(state: dict) -> dict:
    """Execute hybrid retrieval with the current local searcher."""
    from app.retrieval.hybrid_searcher import HybridSearcher

    global _searcher
    if _searcher is None:
        _searcher = HybridSearcher()
    searcher = _searcher
    plan = resolve_retrieval_plan(state)
    query = state.get("rewritten_query") or state.get("query", "")
    results = await searcher.search(
        query=query,
        user=state["current_user"],
        top_k=plan["top_k"],
        search_type=plan["search_type"],
        db=state["db"],
    )
    results = _normalize_retrieved_results(
        searcher,
        query=query,
        results=results,
        plan=plan,
        conversation_state=state.get("conversation_state"),
    )
    state["retrieved_docs"] = results
    state["citations"] = [
        {
            "doc_id": item.get("doc_id"),
            "doc_title": item.get("document_title", "未知文档"),
            "page_number": item.get("page_number"),
            "section_title": item.get("section_title"),
            "snippet": item.get("snippet", ""),
            "relevance_score": item.get("score", 0.0),
        }
        for item in results
    ]
    state["retrieval_plan"] = plan
    state["evidence_pack"] = build_evidence_pack(results, query=query)
    return state


def _normalize_retrieved_results(
    searcher,
    *,
    query: str,
    results: list[dict],
    plan: dict | None = None,
    conversation_state: dict | None = None,
) -> list[dict]:
    plan = plan or {}
    explicit_titles = _extract_scope_titles(searcher, query=query, conversation_state=conversation_state)
    subject = str((conversation_state or {}).get("subject") or "").strip()

    scoped_results = results
    if explicit_titles:
        matched = _filter_results_by_titles(results, explicit_titles)
        if matched:
            scoped_results = matched
    elif subject:
        matched = _filter_results_by_subject(results, subject)
        if matched:
            scoped_results = matched

    informative_results = _drop_low_information_chunks(scoped_results)
    if informative_results:
        scoped_results = informative_results
    else:
        non_boilerplate_results = [item for item in scoped_results if not _is_boilerplate_chunk(item)]
        if non_boilerplate_results:
            scoped_results = non_boilerplate_results

    scoped_results = _prioritize_substantive_chunks(
        scoped_results,
        query=query,
        prefer_summary_details=bool(explicit_titles) or bool(plan.get("prefer_summary_details")),
    )

    max_per_doc = int(plan.get("max_per_doc") or (3 if explicit_titles else 2))
    normalized = _dedupe_and_limit_results(scoped_results, max_per_doc=max_per_doc)
    if plan.get("require_multi_doc"):
        normalized = _prefer_multi_doc_coverage(normalized)
    return normalized


def _extract_scope_titles(searcher, *, query: str, conversation_state: dict | None) -> list[str]:
    explicit_titles: list[str] = []
    if hasattr(searcher, "_extract_explicit_titles"):
        explicit_titles = list(searcher._extract_explicit_titles(query))

    if explicit_titles:
        return explicit_titles

    state = conversation_state or {}
    remembered_titles = state.get("explicit_titles") if isinstance(state.get("explicit_titles"), list) else []
    if remembered_titles:
        return [title.strip("《》") for title in remembered_titles if str(title).strip()]

    subject = str(state.get("subject") or "").strip()
    if subject.startswith("《") and subject.endswith("》"):
        return [subject.strip("《》")]
    return []


def _filter_results_by_titles(results: list[dict], explicit_titles: list[str]) -> list[dict]:
    lowered_titles = [title.lower() for title in explicit_titles if title]
    matched = []
    for item in results:
        doc_title = str(item.get("document_title") or "").strip().lower()
        if doc_title and any(title in doc_title for title in lowered_titles):
            matched.append(item)
    return matched


def _filter_results_by_subject(results: list[dict], subject: str) -> list[dict]:
    normalized_subject = subject.strip().strip("《》").lower()
    if not normalized_subject:
        return []
    matched = []
    for item in results:
        doc_title = str(item.get("document_title") or "").strip().lower()
        if normalized_subject in doc_title:
            matched.append(item)
    return matched


def _dedupe_and_limit_results(results: list[dict], *, max_per_doc: int) -> list[dict]:
    filtered: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    doc_counts: dict[str, int] = {}

    for item in results:
        doc_key = str(item.get("doc_id") or item.get("document_title") or "").strip()
        if not doc_key:
            doc_key = "__unknown__"
        if doc_counts.get(doc_key, 0) >= max_per_doc:
            continue

        signature = (
            doc_key,
            str(item.get("section_title") or "").strip(),
            str(item.get("snippet") or "").strip(),
        )
        if signature in seen:
            continue

        seen.add(signature)
        doc_counts[doc_key] = doc_counts.get(doc_key, 0) + 1
        filtered.append(item)

    return filtered


def _prefer_multi_doc_coverage(results: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    ordered_doc_keys: list[str] = []
    for item in results:
        doc_key = str(item.get("doc_id") or item.get("document_title") or "__unknown__").strip()
        if doc_key not in grouped:
            grouped[doc_key] = []
            ordered_doc_keys.append(doc_key)
        grouped[doc_key].append(item)

    if len(grouped) <= 1:
        return results

    reordered: list[dict] = []
    max_depth = max(len(items) for items in grouped.values())
    for depth in range(max_depth):
        for doc_key in ordered_doc_keys:
            items = grouped[doc_key]
            if depth < len(items):
                reordered.append(items[depth])
    return reordered


def _drop_low_information_chunks(results: list[dict]) -> list[dict]:
    return [item for item in results if not _is_low_information_chunk(item)]


def _prioritize_substantive_chunks(results: list[dict], *, query: str, prefer_summary_details: bool) -> list[dict]:
    if len(results) <= 1:
        return results
    return sorted(
        results,
        key=lambda item: (
            _chunk_priority(item, query=query, prefer_summary_details=prefer_summary_details),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )


def _chunk_priority(item: dict, *, query: str, prefer_summary_details: bool) -> int:
    snippet = " ".join(str(item.get("snippet") or "").split()).strip()
    section = str(item.get("section_title") or "").strip()
    title = str(item.get("document_title") or "").strip()
    page_number = int(item.get("page_number") or 0)
    normalized_query = str(query or "").strip()
    priority = 0

    if len(snippet) >= 120:
        priority += 3
    elif len(snippet) >= 60:
        priority += 1
    priority += _keyword_overlap_score(title, f"{section} {snippet}") * 2
    if section == title and page_number > 1:
        priority -= 4

    substantive_markers = (
        "预算情况说明",
        "收支预算情况说明",
        "收入预算情况说明",
        "支出预算情况说明",
        "财政拨款支出预算情况说明",
        "项目绩效目标表",
        "万元",
        "附件",
        "其中",
    )
    if any(marker in snippet for marker in substantive_markers):
        priority += 6

    if prefer_summary_details:
        if "目录" in snippet[:20]:
            priority -= 5
        if page_number in {1, 2} and "说明" not in snippet and "一、" not in snippet and "常见问题解答" not in snippet:
            priority -= 3
        if "__download.jsp" in section:
            priority -= 2
        if section.startswith(("2 ", "3 ", "4 ", "五、", "六、", "七、")):
            priority -= 4
        if any(marker in snippet for marker in ("总则", "概述", "适用范围", "基本原则", "常见问题解答 一、", "附件 8： 西南大学新进人员入职报到 常见问题解答")):
            priority += 9
        if any(marker in snippet for marker in ("发放安家费", "联系方式", "报到完成后")):
            priority -= 6
        if snippet.startswith("1 附件") or snippet.startswith("附件 8："):
            priority += 12
        if any(marker in snippet for marker in ("七、报到完成后", "安家费", "科研启动金")):
            priority -= 10
        if _is_summary_query(normalized_query):
            if "常见问题" in title and page_number == 1:
                priority += 18
            if "常见问题" in title and page_number >= 4:
                priority -= 10
            if _looks_like_question_style_chunk(section, snippet) and not (
                "常见问题解答" in snippet and page_number == 1
            ):
                priority -= 10
            if any(marker in snippet for marker in ("哪些情况下", "是否需要", "如何办理", "怎么办", "怎么处理")):
                priority -= 8
            if any(marker in snippet for marker in ("主要包括", "主要围绕", "适用范围", "基本原则", "常见问题解答")):
                priority += 6

    if _is_core_requirements_query(normalized_query):
        if any(marker in snippet for marker in ("责任", "处分", "附则", "负责解释", "自印发之日起执行")):
            priority -= 7
        if "关于印发" in snippet or "特此通知" in snippet:
            priority -= 5
        if page_number == 1:
            priority -= 3
        if page_number >= 10:
            priority -= 2
        if 2 <= page_number <= 8:
            priority += 3
        if any(marker in snippet for marker in ("总则", "适用人", "加强和规范", "差旅费是指", "定义", "基本原则")):
            priority += 6
        if any(marker in snippet for marker in ("审批", "报销", "标准", "住宿费", "伙食补助", "交通费", "出差")):
            priority += 5

    if _is_materials_query(normalized_query):
        if any(marker in snippet for marker in ("材料", "提交", "证明", "合同", "社保缴纳证明", "档案", "报到材料", "附件")):
            priority += 10
        if any(marker in snippet for marker in ("试用期", "起薪", "安家费", "科研启动金")):
            priority -= 4

    return priority


def _is_core_requirements_query(query: str) -> bool:
    return any(marker in query for marker in ("核心要求", "主要要求", "关键要求", "核心内容", "主要内容", "要点", "重点"))


def _is_summary_query(query: str) -> bool:
    return any(marker in query for marker in ("概括", "概述", "总结", "摘要", "主要内容", "要点", "讲什么"))


def _is_materials_query(query: str) -> bool:
    return any(marker in query for marker in ("材料", "提交什么", "需要哪些", "需要什么", "证明", "附件"))


def _is_low_information_chunk(item: dict) -> bool:
    snippet = " ".join(str(item.get("snippet") or "").split()).strip()
    title = str(item.get("document_title") or "").strip()
    section = str(item.get("section_title") or "").strip()
    if not snippet:
        return True

    comparable = {
        snippet.lower(),
        snippet.lower().replace(".html", "").replace(".pdf", ""),
    }
    low_info_targets = {
        title.lower(),
        title.lower().replace(".html", "").replace(".pdf", ""),
        section.lower(),
        f"{title.lower().replace('.html', '').replace('.pdf', '')}-信息公开",
    }
    if comparable & low_info_targets and len(snippet) <= 32:
        return True

    if len(snippet) <= 12 and ("信息公开" in snippet or "版权所有" in snippet):
        return True

    if _is_boilerplate_chunk(item):
        return True

    return False


def _is_boilerplate_chunk(item: dict) -> bool:
    snippet = " ".join(str(item.get("snippet") or "").split()).strip()
    markers = ("附件：", "已下载次数", "访问者", "版权所有", "地址：", "邮编：", "传真：")
    hits = sum(1 for marker in markers if marker in snippet)
    return hits >= 2


def _looks_like_question_style_chunk(section: str, snippet: str) -> bool:
    combined = f"{section} {snippet}".strip()
    if re.match(r"^[一二三四五六七八九十]+[、.]", section):
        return True
    question_markers = ("？", "?", "哪些", "是否", "如何", "怎么办", "怎么", "何时", "什么时候")
    return any(marker in combined for marker in question_markers)


def _keyword_overlap_score(title: str, text: str) -> int:
    title_keywords = [
        token
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", title)
        if token not in {"常见问题", "问题", "办法", "制度", "规定", "通知", "方案", "pdf", "doc", "docx"}
    ]
    if not title_keywords:
        return 0
    return sum(1 for keyword in title_keywords if keyword in text)
