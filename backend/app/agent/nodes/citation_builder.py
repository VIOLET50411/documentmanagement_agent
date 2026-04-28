"""Citation Builder Node — Formats source references."""


async def citation_builder(state: dict) -> dict:
    """Build structured citations from retrieved documents."""
    # Format: [Source: Document Title — Page X, §Section]
    citations = []
    for doc in state.get("retrieved_docs", []):
        citations.append({
            "doc_id": doc.get("doc_id", ""),
            "doc_title": doc.get("title", "Unknown"),
            "page_number": doc.get("page_number"),
            "section_title": doc.get("section_title"),
            "snippet": doc.get("content", "")[:200],
            "relevance_score": doc.get("score", 0.0),
        })
    state["citations"] = citations
    return state
