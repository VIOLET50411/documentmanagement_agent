"""Retriever node fallback implementation."""

from __future__ import annotations

_searcher = None

DEFAULT_TOP_K_BY_INTENT = {
    "qa": 5,
    "compare": 8,
    "summarize": 8,
    "graph_query": 6,
}


def resolve_retrieval_plan(state: dict) -> dict:
    """Build a conservative retrieval plan from the current runtime state."""

    intent = str(state.get("intent") or "qa")
    requested_type = str(state.get("search_type") or "hybrid")
    requested_top_k = state.get("top_k")

    if isinstance(requested_top_k, int) and requested_top_k > 0:
        top_k = requested_top_k
    else:
        top_k = DEFAULT_TOP_K_BY_INTENT.get(intent, 5)

    search_type = requested_type
    if intent == "graph_query" and requested_type == "hybrid":
        search_type = "graph"

    return {
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
    results = _normalize_retrieved_results(searcher, query=query, results=results)
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
    return state


def _normalize_retrieved_results(searcher, *, query: str, results: list[dict]) -> list[dict]:
    explicit_titles = []
    if hasattr(searcher, "_extract_explicit_titles"):
        explicit_titles = list(searcher._extract_explicit_titles(query))

    scoped_results = results
    if explicit_titles:
        matched = []
        for item in results:
            doc_title = str(item.get("document_title") or "").strip().lower()
            if doc_title and any(title.lower() in doc_title for title in explicit_titles):
                matched.append(item)
        if matched:
            scoped_results = matched

    informative_results = _drop_low_information_chunks(scoped_results)
    if informative_results:
        scoped_results = informative_results
    else:
        non_boilerplate_results = [item for item in scoped_results if not _is_boilerplate_chunk(item)]
        if non_boilerplate_results:
            scoped_results = non_boilerplate_results

    max_per_doc = 3 if explicit_titles else 2
    return _dedupe_and_limit_results(scoped_results, max_per_doc=max_per_doc)


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


def _drop_low_information_chunks(results: list[dict]) -> list[dict]:
    filtered = [item for item in results if not _is_low_information_chunk(item)]
    return filtered


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
    markers = ("附件【", "已下载次", "访问者", "版权所有", "地址：", "邮编：", "传真：")
    hits = sum(1 for marker in markers if marker in snippet)
    return hits >= 2
