"""Ranking fusion helpers."""

from __future__ import annotations


def reciprocal_rank_fusion(result_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """Combine results from multiple retrieval sources using classic RRF."""
    return weighted_reciprocal_rank_fusion(result_lists, weights=[1.0] * len(result_lists), k=k)


def weighted_reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[dict]:
    """Combine multiple ranked lists with optional per-source weights."""
    if weights is None:
        weights = [1.0] * len(result_lists)

    scores: dict[str, dict] = {}
    for list_index, result_list in enumerate(result_lists):
        weight = weights[list_index] if list_index < len(weights) else 1.0
        for rank, doc in enumerate(result_list, start=1):
            doc_id = doc.get("chunk_id") or doc.get("id") or f"fallback::{list_index}:{rank}"
            if doc_id not in scores:
                scores[doc_id] = {"doc": dict(doc), "score": 0.0}
            scores[doc_id]["score"] += weight * (1.0 / (k + rank))

    sorted_results = sorted(scores.values(), key=lambda item: item["score"], reverse=True)
    return [item["doc"] | {"rrf_score": round(item["score"], 6)} for item in sorted_results]
