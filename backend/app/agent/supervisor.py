"""Fallback multi-agent supervisor."""

from __future__ import annotations

from typing import Optional, TypedDict

import structlog

from app.agent.agents.compliance_agent import ComplianceAgent
from app.agent.agents.critic_agent import CriticAgent
from app.agent.agents.data_agent import DataAgent
from app.agent.agents.graph_agent import GraphAgent
from app.agent.agents.summary_agent import SummaryAgent
from app.agent.nodes.intent_router import intent_router
from app.agent.nodes.query_rewriter import query_rewriter
from app.memory.long_term_memory import LongTermMemory

logger = structlog.get_logger("docmind.supervisor")


class AgentState(TypedDict, total=False):
    messages: list
    query: str
    rewritten_query: str
    intent: str
    retrieved_docs: list
    sql_result: Optional[dict]
    graph_result: Optional[dict]
    answer: str
    citations: list
    agent_used: str
    user_profile: dict
    iteration: int
    critic_approved: bool
    pii_mapping: dict
    db: object
    current_user: object
    search_type: str
    thread_id: str
    trace_id: str
    warnings: list[str]
    tool_calls: list[dict]


class SupervisorAgent:
    """Supervisor agent with deterministic routing fallback."""

    def __init__(self, user_context: dict):
        self.user_context = user_context

    async def route_intent(self, state: AgentState) -> AgentState:
        state = await intent_router(state)
        if state.get("db") is not None and state.get("current_user") is not None:
            state["user_profile"] = await LongTermMemory(state["db"]).get_profile(state["current_user"].id)
        else:
            state["user_profile"] = {}
        return state

    async def dispatch(self, state: AgentState):
        intent = state["intent"]
        if intent == "statistics":
            return DataAgent()
        if intent == "summarize":
            return SummaryAgent()
        if intent == "graph_query":
            return GraphAgent()
        return ComplianceAgent()

    async def run(self, query: str, thread_id: str = None, db=None, current_user=None, messages=None, search_type: str = "hybrid", trace_id: str = ""):
        state: AgentState = {
            "messages": messages or [],
            "query": query,
            "rewritten_query": query,
            "intent": "qa",
            "retrieved_docs": [],
            "sql_result": None,
            "graph_result": None,
            "answer": "",
            "citations": [],
            "agent_used": "",
            "user_profile": {},
            "iteration": 0,
            "critic_approved": False,
            "pii_mapping": {},
            "db": db,
            "current_user": current_user,
            "search_type": search_type,
            "thread_id": thread_id,
            "trace_id": trace_id,
            "warnings": [],
            "tool_calls": [],
        }

        yield {"status": "thinking", "msg": "正在理解您的问题..."}
        try:
            state = await self.route_intent(state)
        except Exception as exc:
            logger.error("supervisor.route_intent_failed", error=str(exc))
            state["warnings"].append(f"route_intent_error: {exc}")

        yield {"status": "reading", "msg": "正在补全上下文并改写查询..."}
        try:
            state = await query_rewriter(state)
        except Exception as exc:
            logger.error("supervisor.query_rewriter_failed", error=str(exc))
            state["warnings"].append(f"query_rewriter_error: {exc}")

        specialist = await self.dispatch(state)
        status_map = {
            "statistics": ("tool_call", "正在执行统计查询..."),
            "summarize": ("reading", "正在整理文档摘要..."),
            "graph_query": ("searching", "正在梳理关联关系..."),
            "compare": ("reading", "正在整理对比项..."),
            "qa": ("searching", "正在检索相关文档..."),
        }
        status, message = status_map.get(state["intent"], ("searching", "正在检索相关文档..."))
        yield {"status": status, "msg": message}

        try:
            state = await specialist.run(state)
        except Exception as exc:
            logger.error("supervisor.specialist_failed", error=str(exc), intent=state["intent"])
            state["answer"] = f"处理过程中出现异常，请稍后重试。（{type(exc).__name__}）"
            state["agent_used"] = "error_fallback"
            state["warnings"].append(f"specialist_error: {exc}")
            yield {"status": "error", "msg": str(exc)[:200]}

        yield {"status": "reading", "msg": "正在检查答案与引用..."}
        try:
            state = await CriticAgent().run(state)
        except Exception as exc:
            logger.error("supervisor.critic_failed", error=str(exc))
            state["critic_approved"] = True
            state["warnings"].append(f"critic_error: {exc}")

        if not state["critic_approved"]:
            state["answer"] = state.get("answer") or "当前无法生成满足要求的答案。"

        yield {
            "status": "done",
            "answer": state["answer"],
            "citations": state.get("citations", []),
            "agent_used": state.get("agent_used"),
            "rewritten_query": state.get("rewritten_query"),
        }

