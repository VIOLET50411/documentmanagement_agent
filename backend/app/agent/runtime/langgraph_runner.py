from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import import_module
from typing import AsyncIterator

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.agents.compliance_agent import ComplianceAgent
from app.agent.agents.critic_agent import CriticAgent
from app.agent.agents.data_agent import DataAgent
from app.agent.agents.graph_agent import GraphAgent
from app.agent.agents.summary_agent import SummaryAgent
from app.agent.nodes.generator import generator
from app.agent.nodes.intent_router import intent_router
from app.agent.nodes.query_rewriter import query_rewriter
from app.agent.nodes.retriever import retriever
from app.agent.nodes.self_correction import self_correction
from app.agent.runtime.langgraph_compat import native_checkpoint_support_status
from app.agent.runtime.checkpoint_store import RuntimeCheckpointStore
from app.config import settings
from app.memory.long_term_memory import LongTermMemory


NODE_STATUS_MAP = {
    "intent_router": ("thinking", "正在理解您的问题..."),
    "query_rewriter": ("reading", "正在补全文并改写查询..."),
    "retriever": ("searching", "正在检索相关文档..."),
    "self_correction": ("reading", "正在评估检索质量..."),
    "generator": ("streaming", "正在生成回答..."),
    "critic": ("reading", "正在检查答案与引用..."),
    "compliance": ("searching", "正在检索相关文档..."),
    "summary": ("reading", "正在整理文档摘要..."),
    "graph": ("searching", "正在梳理关联关系..."),
    "data": ("tool_call", "正在执行统计查询..."),
}


class LangGraphRuntimeRunner:
    """Execute the runtime graph and emit node-level updates."""

    def __init__(self, *, db, current_user, max_iterations: int = 2):
        self.db = db
        self.current_user = current_user
        self.max_iterations = max_iterations
        session_factory = None
        bind = getattr(db, "bind", None)
        if bind is not None:
            session_factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
        self.checkpoints = RuntimeCheckpointStore(db=db, session_factory=session_factory) if (db is not None or session_factory is not None) else None

    async def astream(self, initial_state: dict) -> AsyncIterator[dict]:
        trace_id = str(initial_state.get("trace_id") or "")
        config = self._graph_config(trace_id)
        async with self._native_checkpointer() as checkpointer:
            graph = self._build_graph(checkpointer=checkpointer)
            latest_state = initial_state
            async for event in self._run_until_complete(graph, initial_state, config=config):
                latest_state = event["state"]
                yield event["payload"]
        yield self._done_event(latest_state, agent_fallback="langgraph_runtime")

    async def astream_resume(self, trace_id: str, *, state_overrides: dict | None = None) -> AsyncIterator[dict]:
        if self.checkpoints is None:
            yield {
                "status": "error",
                "msg": "当前未启用 checkpoint 持久化，无法恢复执行。",
                "degraded": True,
                "fallback_reason": "checkpoint_store_unavailable",
                "resume_strategy": "unavailable",
            }
            return

        checkpoint = await self.checkpoints.latest_for_trace(trace_id)
        if checkpoint is None:
            yield {
                "status": "error",
                "msg": "未找到可恢复的运行时检查点，请重新发起请求。",
                "degraded": True,
                "fallback_reason": "checkpoint_not_found",
                "resume_strategy": "not_found",
            }
            return

        state = self.checkpoints.deserialize_payload(checkpoint)
        state.update(state_overrides or {})
        state["trace_id"] = trace_id
        state["warnings"] = list(state.get("warnings") or []) + ["resumed_from_checkpoint"]
        config = self._graph_config(trace_id)

        yield {
            "status": "reading",
            "msg": "已从最近检查点恢复执行...",
            "node_name": checkpoint.node_name,
            "intent": state.get("intent"),
            "rewritten_query": state.get("rewritten_query"),
            "degraded": bool(state.get("degraded", False)),
            "resume_strategy": "checkpoint_load",
            "resume_node": checkpoint.node_name,
        }

        async with self._native_checkpointer() as checkpointer:
            graph = self._build_graph(checkpointer=checkpointer)
            native_state = await self._safe_get_state(graph, config)
            if native_state is not None:
                merged = dict(getattr(native_state, "values", {}) or {})
                merged.update(state)
                state = merged
                next_nodes = tuple(getattr(native_state, "next", ()) or ())
                if next_nodes:
                    async for event in self._run_until_complete(graph, None, config=config):
                        state = event["state"]
                        payload = dict(event["payload"])
                        payload.setdefault("resume_strategy", "native")
                        yield payload
                yield self._done_event(state, agent_fallback="langgraph_runtime_resume", resume_strategy="native")
                return

        next_node = self._next_node_after(checkpoint.node_name, state)
        if next_node is None:
            yield self._done_event(
                state,
                agent_fallback="langgraph_runtime_resume",
                fallback_reason="resume_terminal_checkpoint",
                resume_strategy="terminal",
            )
            return

        while next_node is not None:
            handler = self._node_handler(next_node)
            state = await handler(state)
            payload = await self._emit_node_event(next_node, state)
            payload["resume_strategy"] = "manual"
            payload["resume_node"] = next_node
            yield payload
            next_node = self._next_node_after(next_node, state)

        yield self._done_event(state, agent_fallback="langgraph_runtime_resume", resume_strategy="manual")

    async def _run_until_complete(self, graph, initial_input, *, config: dict) -> AsyncIterator[dict]:
        pending_input = initial_input
        while True:
            async for update in graph.astream(pending_input, config=config, stream_mode="updates"):
                for node_name, node_state in update.items():
                    if not isinstance(node_state, dict):
                        continue
                    yield {
                        "state": node_state,
                        "payload": await self._emit_node_event(node_name, node_state),
                    }
            snapshot = await self._safe_get_state(graph, config)
            if snapshot is None:
                break
            next_nodes = tuple(getattr(snapshot, "next", ()) or ())
            if not next_nodes:
                values = getattr(snapshot, "values", None)
                if isinstance(values, dict):
                    return_state = values
                break
            pending_input = None

    def _build_graph(self, *, checkpointer=None):
        graph = StateGraph(dict)
        graph.add_node("intent_router", self._route_intent)
        graph.add_node("query_rewriter", query_rewriter)
        graph.add_node("retriever", self._retriever)
        graph.add_node("self_correction", self_correction)
        graph.add_node("generator", generator)
        graph.add_node("critic", self._critic)
        graph.add_node("compliance", self._compliance)
        graph.add_node("summary", self._summary)
        graph.add_node("graph", self._graph)
        graph.add_node("data", self._data)

        graph.set_entry_point("intent_router")
        graph.add_edge("intent_router", "query_rewriter")
        graph.add_conditional_edges(
            "query_rewriter",
            self._route_after_rewrite,
            {
                "retriever": "retriever",
                "compliance": "compliance",
                "summary": "summary",
                "graph": "graph",
                "data": "data",
            },
        )
        graph.add_edge("retriever", "self_correction")
        graph.add_conditional_edges(
            "self_correction",
            self._route_after_self_correction,
            {
                "query_rewriter": "query_rewriter",
                "generator": "generator",
            },
        )
        graph.add_edge("generator", "critic")
        graph.add_edge("compliance", "critic")
        graph.add_edge("summary", "critic")
        graph.add_edge("graph", "critic")
        graph.add_edge("data", "critic")
        graph.add_conditional_edges(
            "critic",
            self._route_after_critic,
            {
                "retry_qa": "retriever",
                "retry_compliance": "compliance",
                "retry_summary": "summary",
                "retry_graph": "graph",
                "retry_data": "data",
                "end": END,
            },
        )
        if checkpointer is not None:
            return graph.compile(checkpointer=checkpointer, interrupt_after="*")
        return graph.compile()

    @asynccontextmanager
    async def _native_checkpointer(self):
        status = native_checkpoint_support_status()
        if not status.get("available"):
            yield None
            return
        AsyncPostgresSaver = self._load_async_postgres_saver()
        if AsyncPostgresSaver is None:
            yield None
            return
        conn_string = self._native_checkpoint_conn_string()
        async with AsyncPostgresSaver.from_conn_string(conn_string, pipeline=False) as saver:
            await saver.setup()
            yield saver

    def _load_async_postgres_saver(self):
        try:
            module = import_module("langgraph.checkpoint.postgres.aio")
        except ImportError:  # pragma: no cover - optional dependency
            return None
        return getattr(module, "AsyncPostgresSaver", None)

    def _native_checkpoint_conn_string(self) -> str:
        password = settings.postgres_password.replace("@", "%40")
        return f"postgresql://{settings.postgres_user}:{password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"

    def _graph_config(self, trace_id: str) -> dict:
        return {"configurable": {"thread_id": trace_id}}

    async def _safe_get_state(self, graph, config: dict):
        try:
            if hasattr(graph, "aget_state"):
                return await graph.aget_state(config)
            return graph.get_state(config)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
            return None

    async def _emit_node_event(self, node_name: str, node_state: dict) -> dict:
        if self.checkpoints is not None:
            await self.checkpoints.save(
                session_id=str(node_state.get("thread_id") or node_state.get("session_id") or ""),
                tenant_id=str(getattr(self.current_user, "tenant_id", "default")),
                trace_id=str(node_state.get("trace_id") or ""),
                node_name=node_name,
                iteration=int(node_state.get("iteration", 0) or 0),
                payload=self._checkpoint_payload(node_state),
            )
        status, message = NODE_STATUS_MAP.get(node_name, ("reading", "正在处理请求..."))
        return {
            "status": status,
            "msg": message,
            "node_name": node_name,
            "intent": node_state.get("intent"),
            "rewritten_query": node_state.get("rewritten_query"),
            "degraded": bool(node_state.get("degraded", False)),
        }

    def _done_event(
        self,
        state: dict,
        *,
        agent_fallback: str,
        fallback_reason: str | None = None,
        resume_strategy: str | None = None,
    ) -> dict:
        return {
            "status": "done",
            "answer": state.get("answer", ""),
            "citations": state.get("citations", []),
            "agent_used": state.get("agent_used") or state.get("selected_agent") or agent_fallback,
            "rewritten_query": state.get("rewritten_query"),
            "degraded": bool(state.get("degraded", False)),
            "fallback_reason": fallback_reason,
            "checkpoint_iteration": int(state.get("iteration", 0) or 0),
            "resume_strategy": resume_strategy,
        }

    async def _route_intent(self, state: dict) -> dict:
        state = await intent_router(state)
        if self.db is not None and self.current_user is not None:
            state["user_profile"] = await LongTermMemory(self.db).get_profile(self.current_user.id)
        else:
            state["user_profile"] = {}
        return state

    async def _retriever(self, state: dict) -> dict:
        enriched = await retriever(self._with_runtime_context(state))
        return self._strip_runtime_context(enriched)

    async def _critic(self, state: dict) -> dict:
        return await CriticAgent().run(state)

    async def _compliance(self, state: dict) -> dict:
        state = await ComplianceAgent().run(self._with_runtime_context(state))
        state = self._strip_runtime_context(state)
        state["selected_agent"] = "compliance"
        return state

    async def _summary(self, state: dict) -> dict:
        state = await SummaryAgent().run(self._with_runtime_context(state))
        state = self._strip_runtime_context(state)
        state["selected_agent"] = "summary"
        return state

    async def _graph(self, state: dict) -> dict:
        state = await GraphAgent().run(self._with_runtime_context(state))
        state = self._strip_runtime_context(state)
        state["selected_agent"] = "graph"
        return state

    async def _data(self, state: dict) -> dict:
        state = await DataAgent().run(self._with_runtime_context(state))
        state = self._strip_runtime_context(state)
        state["selected_agent"] = "data"
        return state

    def _node_handler(self, node_name: str):
        return {
            "intent_router": self._route_intent,
            "query_rewriter": query_rewriter,
            "retriever": self._retriever,
            "self_correction": self_correction,
            "generator": generator,
            "critic": self._critic,
            "compliance": self._compliance,
            "summary": self._summary,
            "graph": self._graph,
            "data": self._data,
        }[node_name]

    def _next_node_after(self, node_name: str, state: dict) -> str | None:
        if node_name == "intent_router":
            return "query_rewriter"
        if node_name == "query_rewriter":
            return self._route_after_rewrite(state)
        if node_name == "retriever":
            return "self_correction"
        if node_name == "self_correction":
            return self._route_after_self_correction(state)
        if node_name in {"generator", "compliance", "summary", "graph", "data"}:
            return "critic"
        if node_name == "critic":
            branch = self._route_after_critic(state)
            if branch == "retry_qa":
                return "retriever"
            if branch == "retry_compliance":
                return "compliance"
            if branch == "retry_summary":
                return "summary"
            if branch == "retry_graph":
                return "graph"
            if branch == "retry_data":
                return "data"
            return None
        return None

    def _with_runtime_context(self, state: dict) -> dict:
        enriched = dict(state)
        enriched["db"] = self.db
        enriched["current_user"] = self.current_user
        return enriched

    def _strip_runtime_context(self, state: dict) -> dict:
        cleaned = dict(state)
        cleaned.pop("db", None)
        cleaned.pop("current_user", None)
        return cleaned

    def _route_after_rewrite(self, state: dict) -> str:
        intent = state.get("intent")
        if intent == "statistics":
            return "data"
        if intent == "summarize":
            return "summary"
        if intent == "graph_query":
            return "graph"
        if intent == "compare":
            return "compliance"
        return "retriever"

    def _route_after_self_correction(self, state: dict) -> str:
        if state.get("retrieval_sufficient"):
            return "generator"
        if int(state.get("iteration", 0) or 0) >= self.max_iterations:
            state["degraded"] = True
            state["warnings"] = list(state.get("warnings") or []) + ["retrieval_insufficient"]
            return "generator"
        return "query_rewriter"

    def _route_after_critic(self, state: dict) -> str:
        if state.get("critic_approved"):
            return "end"
        if int(state.get("iteration", 0) or 0) >= self.max_iterations:
            state["degraded"] = True
            state["warnings"] = list(state.get("warnings") or []) + ["critic_not_approved"]
            return "end"
        if state.get("intent") == "qa":
            return "retry_qa"
        if state.get("intent") == "summarize":
            return "retry_summary"
        if state.get("intent") == "graph_query":
            return "retry_graph"
        if state.get("intent") == "statistics":
            return "retry_data"
        return "retry_compliance"

    def _checkpoint_payload(self, state: dict) -> dict:
        return {
            "query": state.get("query"),
            "rewritten_query": state.get("rewritten_query"),
            "intent": state.get("intent"),
            "iteration": state.get("iteration", 0),
            "thread_id": state.get("thread_id"),
            "session_id": state.get("session_id"),
            "search_type": state.get("search_type"),
            "selected_agent": state.get("selected_agent"),
            "task_mode": state.get("task_mode"),
            "agent_used": state.get("agent_used"),
            "retrieval_sufficient": state.get("retrieval_sufficient"),
            "critic_approved": state.get("critic_approved"),
            "degraded": bool(state.get("degraded", False)),
            "fallback_reason": state.get("fallback_reason"),
            "warnings": state.get("warnings", []),
            "citations": state.get("citations", []),
            "retrieved_docs": state.get("retrieved_docs", []),
            "evidence_pack": state.get("evidence_pack", {}),
            "messages": state.get("messages", []),
            "conversation_state": state.get("conversation_state", {}),
            "answer_preview": (state.get("answer") or "")[:500],
            "answer": state.get("answer") or "",
        }
