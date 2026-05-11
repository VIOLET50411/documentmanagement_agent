"""Deterministic intent router for runtime graph execution."""

from __future__ import annotations

import re


STATISTICS_KEYWORDS = (
    "统计",
    "数量",
    "多少",
    "几份",
    "总数",
    "占比",
    "平均",
    "汇总",
    "报表",
    "count",
    "total",
    "average",
    "metric",
)

COMPARE_KEYWORDS = (
    "对比",
    "比较",
    "区别",
    "差异",
    "变化",
    "前后",
    "版本",
    "compare",
    "difference",
    "versus",
    "vs",
)

SUMMARY_KEYWORDS = (
    "总结",
    "摘要",
    "概括",
    "梳理",
    "总结一下",
    "主要内容",
    "要点",
    "summary",
    "summarize",
)

GRAPH_KEYWORDS = (
    "关系",
    "关联",
    "依赖",
    "链路",
    "审批链",
    "审批流程",
    "谁负责",
    "负责人",
    "角色职责",
    "上下游",
    "影响",
    "graph",
    "relationship",
    "owner",
)


async def intent_router(state: dict) -> dict:
    """Route a query into a stable intent label for downstream agents."""
    query = str(state.get("query") or "").strip()
    lowered = query.lower()

    if _looks_like_compare(query, lowered):
        intent = "compare"
    elif _looks_like_statistics(query, lowered):
        intent = "statistics"
    elif _looks_like_graph(query, lowered):
        intent = "graph_query"
    elif _looks_like_summary(query, lowered):
        intent = "summarize"
    else:
        intent = "qa"

    state["intent"] = intent
    state["task_mode"] = _derive_task_mode(query, intent)
    return state


def _looks_like_statistics(query: str, lowered: str) -> bool:
    if any(keyword in query or keyword in lowered for keyword in STATISTICS_KEYWORDS):
        return True
    return bool(re.search(r"\b(count|total|avg|sum)\b", lowered))


def _looks_like_compare(query: str, lowered: str) -> bool:
    if any(keyword in query or keyword in lowered for keyword in COMPARE_KEYWORDS):
        return True
    return "和" in query and any(token in query for token in ("差异", "区别", "不同"))


def _looks_like_summary(query: str, lowered: str) -> bool:
    return any(keyword in query or keyword in lowered for keyword in SUMMARY_KEYWORDS)


def _looks_like_graph(query: str, lowered: str) -> bool:
    return any(keyword in query or keyword in lowered for keyword in GRAPH_KEYWORDS)


def _derive_task_mode(query: str, intent: str) -> str:
    normalized = str(query or "").strip()
    if intent == "compare":
        return "compare"
    if intent == "summarize":
        return "summary"
    if intent == "statistics":
        return "extract"
    if intent == "graph_query":
        return "process"
    if any(token in normalized for token in ("起草", "撰写", "写一份", "生成一份", "草拟", "写一个")):
        return "draft"
    if any(token in normalized for token in ("流程", "步骤", "怎么走", "如何办理", "审批链", "链路")):
        return "process"
    if any(token in normalized for token in ("材料", "条件", "金额", "标准", "负责人", "依据", "适用范围")):
        return "extract"
    return "qa"
