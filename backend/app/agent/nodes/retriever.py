"""Retriever node fallback implementation."""

from __future__ import annotations


async def retriever(state: dict) -> dict:
    """Execute hybrid retrieval with the current local searcher."""
    from app.retrieval.hybrid_searcher import HybridSearcher

    searcher = HybridSearcher()
    results = await searcher.search(
        query=state.get("rewritten_query") or state.get("query", ""),
        user=state["current_user"],
        top_k=state.get("top_k", 5),
        search_type=state.get("search_type", "hybrid"),
        db=state["db"],
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
    return state
