"""Data agent implementation."""

from __future__ import annotations

import time

from app.agent.runtime.permission_gate import PermissionGate
from app.agent.runtime.tool_registry import ToolResultEnvelope, build_default_registry
from app.agent.tools.text2sql import Text2SQLTool
from app.dependencies import get_redis
from app.services.security_audit_service import SecurityAuditService


class DataAgent:
    """Specialist agent for data analysis queries."""

    async def run(self, state: dict) -> dict:
        tool_name = "text2sql"
        registry = build_default_registry()
        spec = registry.resolve(tool_name)
        gate = PermissionGate(get_redis())
        decision = await gate.evaluate(
            tool=spec,
            user_context={
                "user_id": getattr(state.get("current_user"), "id", None),
                "tenant_id": getattr(state.get("current_user"), "tenant_id", "default"),
                "role": getattr(state.get("current_user"), "role", "VIEWER"),
            },
            trace_id=state.get("trace_id"),
        )

        db_for_audit = state.get("db")
        if hasattr(db_for_audit, "add") and hasattr(db_for_audit, "flush"):
            await SecurityAuditService(get_redis(), db_for_audit).log_event(
                getattr(state.get("current_user"), "tenant_id", "default"),
                "runtime_tool_decision",
                {"allow": "low", "ask": "medium", "deny": "high"}.get(decision.decision, "medium"),
                f"{tool_name} -> {decision.decision} ({decision.reason})",
                user_id=getattr(state.get("current_user"), "id", None),
                target=tool_name,
                result=decision.decision,
                trace_id=state.get("trace_id"),
                metadata={
                    "tool_name": tool_name,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "source": decision.source,
                },
            )

        state.setdefault("tool_calls", []).append(
            {
                "tool_name": tool_name,
                "decision": decision.decision,
                "reason": decision.reason,
                "source": decision.source,
            }
        )

        if decision.decision == "deny":
            state["sql_result"] = {"status": "denied", "results": [], "sql": ""}
            state["answer"] = "当前权限不允许执行数据查询工具。"
            state["citations"] = []
            state["agent_used"] = "data"
            state.setdefault("warnings", []).append("tool_denied:text2sql")
            return state

        if decision.decision == "ask":
            state["sql_result"] = {"status": "approval_required", "results": [], "sql": ""}
            state["answer"] = "当前查询需要更高权限，请联系管理员授权后重试。"
            state["citations"] = []
            state["agent_used"] = "data"
            state.setdefault("warnings", []).append("tool_ask:text2sql")
            return state

        tool = Text2SQLTool(state["db"])
        state["db"].info["tenant_id"] = state["current_user"].tenant_id
        started = time.perf_counter()
        result = await tool.generate_and_execute(state.get("rewritten_query") or state["query"])
        duration_ms = int((time.perf_counter() - started) * 1000)

        envelope = ToolResultEnvelope(
            ok=result.get("status") == "ok",
            data=result,
            error=None if result.get("status") == "ok" else result.get("status"),
            duration_ms=duration_ms,
        )
        state["tool_result"] = envelope.to_dict()
        state["sql_result"] = result

        if result["status"] == "ok" and result["results"]:
            row = result["results"][0]
            key, value = next(iter(row.items()))
            metric_label = {
                "total_documents": "文档总数",
                "ready_documents": "已完成文档数",
                "processing_documents": "处理中任务数",
                "failed_documents": "失败文档数",
                "average_rating": "平均反馈评分",
                "total_chunks": "总分块数",
            }.get(key, key)
            state["answer"] = f"统计结论：{metric_label} = {value}\n\n执行 SQL：{result['sql']}"
        elif result["status"] == "ok":
            state["answer"] = f"查询已执行，但当前没有返回数据。\n\n执行 SQL：{result['sql']}"
        else:
            state["answer"] = "当前规则模式仅支持文档数量、处理状态、分块数量和反馈评分等统计问题。"

        state["citations"] = []
        state["agent_used"] = "data"
        return state
