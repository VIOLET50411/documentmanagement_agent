"""工具执行节点：执行工具调用并将结果注入 state。"""

from __future__ import annotations

import structlog

logger = structlog.get_logger("docmind.tool_executor")


async def tool_executor(state: dict) -> dict:
    """执行工具调用，将结果作为额外上下文传给生成器。"""
    tool_decision = state.get("tool_decision") or {}
    tool_name = tool_decision.get("tool", "")

    if not tool_name:
        logger.debug("tool_executor.skip", reason="no_tool")
        return state

    query = state.get("rewritten_query") or state.get("query") or ""

    try:
        if tool_name == "text2sql":
            result = await _execute_text2sql(query, state)
        elif tool_name == "calculator":
            result = await _execute_calculator(query)
        else:
            logger.warning("tool_executor.unknown_tool", tool=tool_name)
            return state

        if result:
            state["tool_result"] = {
                "tool": tool_name,
                "success": True,
                "data": result,
            }
            state["tool_calls"] = list(state.get("tool_calls") or []) + [
                {"tool": tool_name, "query": query[:100], "success": True}
            ]
            logger.info("tool_executor.success", tool=tool_name)

    except Exception as exc:  # noqa: BLE001
        logger.warning("tool_executor.failed", tool=tool_name, error=str(exc))
        state["tool_result"] = {
            "tool": tool_name,
            "success": False,
            "error": str(exc),
        }

    return state


async def _execute_text2sql(query: str, state: dict) -> dict | None:
    """执行 text2sql 工具。"""
    try:
        from app.agent.tools.text2sql import Text2SQLTool
        tool = Text2SQLTool()
        db = state.get("db")
        if db is None:
            return None
        result = await tool.generate_and_execute(query=query, db=db)
        return result
    except ImportError:
        logger.warning("tool_executor.text2sql_import_failed")
        return None


async def _execute_calculator(query: str) -> dict | None:
    """执行计算器工具。"""
    try:
        from app.agent.tools.calculator import CalculatorTool
        tool = CalculatorTool()
        result = await tool.evaluate(query)
        return {"expression": query, "result": result}
    except (ImportError, AttributeError):
        logger.warning("tool_executor.calculator_import_failed")
        return None
