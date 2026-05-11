"""Evidence organization helpers for document-grounded answering."""

from __future__ import annotations

import re


EVIDENCE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("process", ("流程", "步骤", "审批", "提交", "审核", "报销", "办理", "登记")),
    ("requirements", ("应当", "不得", "需要", "要求", "标准", "条件", "范围", "材料", "依据", "负责")),
    ("versioning", ("版本", "修订", "生效", "执行", "印发", "年份", "日期")),
    ("numeric", ("万元", "%", "预算", "决算", "金额", "收入", "支出", "财政")),
    ("exception", ("除外", "例外", "特殊", "但是", "如有", "超出", "负担")),
)


def build_evidence_pack(results: list[dict], *, query: str) -> dict:
    """Convert raw retrieval results into a structured evidence bundle."""
    docs: list[dict] = []
    grouped: dict[str, dict] = {}
    salient_points: list[dict] = []
    seen_points: set[str] = set()

    for item in results:
        title = str(item.get("document_title") or "未知文档").strip()
        doc_key = str(item.get("doc_id") or title).strip() or title
        snippet = _normalize_text(item.get("snippet") or "")
        if not snippet:
            continue
        section = str(item.get("section_title") or "未命名章节").strip() or "未命名章节"
        page_number = item.get("page_number")
        category = classify_evidence(snippet, query=query, section_title=section)
        point = {
            "doc_id": item.get("doc_id"),
            "doc_key": doc_key,
            "doc_title": title,
            "section_title": section,
            "page_number": page_number,
            "snippet": snippet,
            "score": float(item.get("score") or 0.0),
            "category": category,
        }

        bucket = grouped.setdefault(
            doc_key,
            {
                "doc_id": item.get("doc_id"),
                "doc_title": title,
                "points": [],
                "categories": set(),
            },
        )
        bucket["points"].append(point)
        bucket["categories"].add(category)

        signature = f"{doc_key}::{section}::{snippet[:120]}"
        if signature not in seen_points:
            seen_points.add(signature)
            salient_points.append(point)

    for bucket in grouped.values():
        ordered_points = sorted(bucket["points"], key=lambda item: (item["category"] != "requirements", -item["score"]))
        docs.append(
            {
                "doc_id": bucket["doc_id"],
                "doc_title": bucket["doc_title"],
                "categories": sorted(bucket["categories"]),
                "points": ordered_points,
            }
        )

    category_counts: dict[str, int] = {}
    for point in salient_points:
        category_counts[point["category"]] = category_counts.get(point["category"], 0) + 1

    dominant_category = max(category_counts.items(), key=lambda item: item[1])[0] if category_counts else "general"
    return {
        "documents": docs,
        "salient_points": salient_points[:8],
        "category_counts": category_counts,
        "dominant_category": dominant_category,
        "document_count": len(docs),
    }


def classify_evidence(snippet: str, *, query: str, section_title: str = "") -> str:
    normalized = " ".join((snippet or "").split()).strip()
    normalized_query = str(query or "").strip()
    section = str(section_title or "").strip()

    if _looks_like_table(normalized):
        return "numeric"

    for category, markers in EVIDENCE_CATEGORY_RULES:
        if any(marker in normalized or marker in section or marker in normalized_query for marker in markers):
            return category

    if re.search(r"\d{4}年|\d{4}-\d{1,2}-\d{1,2}", normalized):
        return "versioning"
    return "general"


def _looks_like_table(text: str) -> bool:
    return text.count("|") >= 6 or bool(re.search(r"\d[\d,]{2,}(?:\.\d+)?", text))


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) > 260:
        return normalized[:257].rstrip() + "..."
    return normalized
