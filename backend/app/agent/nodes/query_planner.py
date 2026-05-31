"""查询规划器：分析复杂查询是否需要分解为多个子查询。"""

from __future__ import annotations

import json
import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.query_planner")

QUERY_PLANNER_SYSTEM_PROMPT = """你是企业文档检索系统的查询规划器。分析用户查询是否需要分解为多个子查询来分别检索。

判断标准：
1. 查询涉及多个不同主题或文档的对比/比较 → 需要分解
2. 查询要求分别列出多个事项的信息 → 需要分解
3. 查询只是关于单一主题的单一问题 → 不需要分解

输出 JSON 格式：
{
    "needs_decomposition": true/false,
    "sub_queries": ["子查询1", "子查询2"],
    "synthesis_strategy": "compare/merge/enumerate"
}

策略说明：
- compare：对比分析（适用于比较、区别、差异类问题）
- merge：综合整理（适用于多个相关信息汇总类问题）
- enumerate：分主题展开（适用于分别列举类问题）

限制：
- 最多 4 个子查询
- 每个子查询应能独立检索
- 仅输出 JSON，不要附加解释"""

# ── 复杂查询模式 ──
_COMPARE_PATTERNS = re.compile(r"(对比|比较|区别|差异|不同之处|有什么不同|哪里不同)")
_ENUMERATE_PATTERNS = re.compile(r"(分别|各自|各有|每个|逐一|一一)")
_MULTI_SUBJECT_PATTERN = re.compile(r"《[^》]+》.*(?:和|与|及|跟|还有).*《[^》]+》")

# 对比/比较类关键词
_COMPLEX_KEYWORDS = (
    "对比", "比较", "区别", "差异", "不同",
    "分别", "各自", "各有", "每个",
)


def _is_complex_query(query: str) -> bool:
    """判断查询是否为复杂查询（可能需要分解）。"""
    if any(keyword in query for keyword in _COMPLEX_KEYWORDS):
        return True
    if _MULTI_SUBJECT_PATTERN.search(query):
        return True
    return False


def _rule_based_decompose(query: str) -> dict | None:
    """规则回退：识别对比模式和分别模式进行分解。"""
    # 对比模式：包含两个书名号标题
    titles = re.findall(r"《([^》]+)》", query)
    if len(titles) >= 2 and _COMPARE_PATTERNS.search(query):
        sub_queries = [f"《{title}》的主要内容和要点" for title in titles[:4]]
        return {
            "needs_decomposition": True,
            "sub_queries": sub_queries,
            "synthesis_strategy": "compare",
        }

    # 分别模式：包含"分别""各自"等
    if _ENUMERATE_PATTERNS.search(query) and len(titles) >= 2:
        sub_queries = [f"《{title}》的相关内容" for title in titles[:4]]
        return {
            "needs_decomposition": True,
            "sub_queries": sub_queries,
            "synthesis_strategy": "enumerate",
        }

    # 对比模式但无书名号：用"和""与"分割
    if _COMPARE_PATTERNS.search(query):
        parts = re.split(r"[和与及跟]", re.sub(r"(对比|比较|区别|差异|不同之处|有什么不同|哪里不同).*$", "", query).strip())
        parts = [p.strip() for p in parts if p.strip() and len(p.strip()) >= 2]
        if len(parts) >= 2:
            compare_aspect = _COMPARE_PATTERNS.search(query)
            aspect = compare_aspect.group(1) if compare_aspect else "内容"
            sub_queries = [f"{part}的{aspect}相关内容" for part in parts[:4]]
            return {
                "needs_decomposition": True,
                "sub_queries": sub_queries,
                "synthesis_strategy": "compare",
            }

    return None


def _parse_planner_result(raw: str) -> dict | None:
    """解析 LLM 输出的 JSON 规划结果。"""
    text = raw.strip()
    # 尝试提取 JSON 块
    json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if json_match:
        text = json_match.group(0)

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        needs = bool(data.get("needs_decomposition", False))
        sub_queries = data.get("sub_queries", [])
        strategy = str(data.get("synthesis_strategy", "merge"))

        if not needs:
            return {"needs_decomposition": False, "sub_queries": [], "synthesis_strategy": ""}

        if not isinstance(sub_queries, list) or not sub_queries:
            return None

        # 限制最多 4 个子查询
        sub_queries = [str(q).strip() for q in sub_queries if str(q).strip()][:4]
        if not sub_queries:
            return None

        # 验证策略
        if strategy not in ("compare", "merge", "enumerate"):
            strategy = "merge"

        return {
            "needs_decomposition": True,
            "sub_queries": sub_queries,
            "synthesis_strategy": strategy,
        }
    except json.JSONDecodeError:
        return None


async def _execute_sub_query(state: dict, sub_query: str) -> list[dict]:
    """对单个子查询执行检索，返回检索结果。"""
    from app.agent.nodes.retriever import retriever

    sub_state = dict(state)
    sub_state["rewritten_query"] = sub_query
    sub_state["query"] = sub_query
    sub_state = await retriever(sub_state)
    return sub_state.get("retrieved_docs") or []


async def query_planner(state: dict) -> dict:
    """查询规划器：分析复杂查询并分解为子查询执行检索。"""
    query = state.get("rewritten_query") or state.get("query") or ""

    # 简单查询直接跳过
    if not _is_complex_query(query):
        state["needs_decomposition"] = False
        state["planner_source"] = "skip"
        return state

    # 尝试 LLM 规划
    llm = LLMService()
    plan = None
    if not llm.is_rule_only:
        try:
            result = await llm.generate(
                system_prompt=QUERY_PLANNER_SYSTEM_PROMPT,
                user_prompt=f"用户查询：{query}",
                temperature=0.1,
                max_tokens=512,
            )
            if result:
                plan = _parse_planner_result(result)
                if plan:
                    state["planner_source"] = "llm"
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.warning("query_planner.llm_failed", error=str(exc))

    # 规则回退
    if plan is None:
        plan = _rule_based_decompose(query)
        if plan:
            state["planner_source"] = "rule_fallback"

    # 不需要分解
    if plan is None or not plan.get("needs_decomposition"):
        state["needs_decomposition"] = False
        state["planner_source"] = state.get("planner_source", "no_decomposition")
        return state

    # 执行子查询检索
    sub_queries = plan["sub_queries"]
    synthesis_strategy = plan["synthesis_strategy"]
    sub_results: list[dict] = []

    for sub_query in sub_queries:
        try:
            docs = await _execute_sub_query(state, sub_query)
            sub_results.append({
                "sub_query": sub_query,
                "retrieved_docs": docs,
            })
            logger.info(
                "query_planner.sub_query_done",
                sub_query=sub_query[:60],
                doc_count=len(docs),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "query_planner.sub_query_failed",
                sub_query=sub_query[:60],
                error=str(exc),
            )
            sub_results.append({
                "sub_query": sub_query,
                "retrieved_docs": [],
            })

    state["needs_decomposition"] = True
    state["sub_queries"] = sub_queries
    state["sub_results"] = sub_results
    state["synthesis_strategy"] = synthesis_strategy

    logger.info(
        "query_planner.decomposed",
        sub_query_count=len(sub_queries),
        strategy=synthesis_strategy,
    )
    return state
