"""工具路由节点：判断查询是否需要工具调用。"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger("docmind.tool_router")

# 工具触发关键词
_TOOL_PATTERNS = {
    "text2sql": re.compile(
        r"(多少|数量|统计|总计|合计|汇总|平均|最高|最低|排名|占比|百分比|增长率|趋势"
        r"|同比|环比|top\s*\d|前\s*\d|各部门.*数|各.*部门.*量)"
    ),
    "calculator": re.compile(
        r"(计算|算一下|乘以|除以|加上|减去|\d+\s*[\+\-\*\/×÷]\s*\d+|百分之)"
    ),
}


async def tool_router(state: dict) -> dict:
    """判断是否需要工具调用，设置 tool_decision。"""
    query = state.get("rewritten_query") or state.get("query") or ""
    intent = state.get("intent") or "qa"

    # statistics 意图直接走 data agent（已有路由），跳过
    if intent == "statistics":
        state["tool_decision"] = {"needed": False, "reason": "routed_to_data_agent"}
        return state

    # 检测工具需求
    for tool_name, pattern in _TOOL_PATTERNS.items():
        if pattern.search(query):
            state["tool_decision"] = {
                "needed": True,
                "tool": tool_name,
                "reason": f"query matches {tool_name} pattern",
            }
            logger.info("tool_router.detected", tool=tool_name, query=query[:60])
            return state

    state["tool_decision"] = {"needed": False, "reason": "no_tool_match"}
    return state
