"""AgentRuntime v2 engine with SSE-friendly events."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from app.agent.runtime.agent_definitions import load_agent_definitions
from app.agent.runtime.permission_gate import PermissionDecision, PermissionGate
from app.agent.runtime.task_store import TaskStore
from app.agent.runtime.tool_registry import build_default_registry
from app.agent.runtime.types import RuntimeEvent, RuntimeRequest, RuntimeState
from app.config import settings
from app.services.security_audit_service import SecurityAuditService


class AgentRuntime:
    """Runtime wrapper that orchestrates supervisor execution and reliability metadata."""

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.task_store = TaskStore(redis_client, retention_seconds=settings.runtime_task_retention_seconds)
        self.tool_registry = build_default_registry()
        self.permission_gate = PermissionGate(redis_client)
        self.agent_definitions = load_agent_definitions(
            Path(__file__).resolve().parents[1] / "extensions",
            enabled_tools={spec.name for spec in self.tool_registry.list()},
        )
        self._sequence = 0

    async def run(self, request: RuntimeRequest, *, db, current_user) -> AsyncIterator[dict]:
        trace_id = str(uuid.uuid4())
        state = RuntimeState(
            session_id=request.thread_id or str(uuid.uuid4()),
            tenant_id=str(request.user_context.get("tenant_id") or "default"),
            query=request.query,
            rewritten_query=request.query,
            trace_id=trace_id,
        )
        task = await self.task_store.register(
            task_type="chat",
            description="Chat runtime execution",
            tenant_id=state.tenant_id,
            trace_id=trace_id,
            session_id=state.session_id,
        )
        await self.task_store.update(task.task_id, status="running")

        start_time = time.perf_counter()
        first_event_sent = False
        runtime_error: str | None = None
        deny_count = 0
        retry_count = 0
        tool_calls = 0

        try:
            retrieval_spec = self.tool_registry.resolve("retrieval.search")
            decision = await self.permission_gate.evaluate(tool=retrieval_spec, user_context=request.user_context, trace_id=trace_id)
            tool_calls = 1
            await self._audit_tool_decision(decision, db=db)
            if decision.decision == "deny":
                deny_count = 1
                event = self._event(
                    status="error",
                    trace_id=trace_id,
                    source="permission_gate",
                    degraded=True,
                    fallback_reason=decision.reason,
                    data={"msg": "当前会话无检索权限，已拒绝请求。"},
                )
                await self._persist_event(state.tenant_id, trace_id, event.as_payload())
                yield event.as_payload()
                await self.task_store.fail(task.task_id, decision.reason)
                return

            from app.agent.runtime.langgraph_runner import LangGraphRuntimeRunner

            graph_runner = LangGraphRuntimeRunner(
                db=db,
                current_user=current_user,
                max_iterations=2,
            )
            timeout_seconds = max(settings.runtime_stage_timeout_seconds, 5)
            async with asyncio.timeout(timeout_seconds):
                async for event in graph_runner.astream(
                    {
                        "messages": request.history,
                        "query": request.query,
                        "rewritten_query": request.query,
                        "intent": "qa",
                        "task_mode": "qa",
                        "retrieved_docs": [],
                        "evidence_pack": {},
                        "sql_result": None,
                        "graph_result": None,
                        "answer": "",
                        "citations": [],
                        "agent_used": "",
                        "selected_agent": "",
                        "user_profile": {},
                        "iteration": 0,
                        "critic_approved": False,
                        "pii_mapping": {},
                        "search_type": request.search_type,
                        "thread_id": request.thread_id,
                        "session_id": state.session_id,
                        "conversation_state": {},
                        "trace_id": trace_id,
                        "warnings": [],
                        "tool_calls": [],
                        "degraded": False,
                    }
                ):
                    runtime_event = self._event(
                        status=event.get("status", "streaming"),
                        trace_id=trace_id,
                        source="agent_runtime_v2",
                        degraded=bool(event.get("degraded", False)),
                        fallback_reason=event.get("fallback_reason"),
                        data={k: v for k, v in event.items() if k != "status"},
                    )
                    await self._persist_event(state.tenant_id, trace_id, runtime_event.as_payload())
                    first_event_sent = True
                    yield runtime_event.as_payload()
        except TimeoutError:
            runtime_error = "runtime_timeout"
            retry_count = 1
            if not first_event_sent:
                degraded_event = self._event(
                    status="thinking",
                    trace_id=trace_id,
                    source="agent_runtime_v2",
                    degraded=True,
                    fallback_reason=runtime_error,
                    data={"msg": "请求处理超时，正在切换到降级响应路径..."},
                )
                await self._persist_event(state.tenant_id, trace_id, degraded_event.as_payload())
                yield degraded_event.as_payload()
                first_event_sent = True

            done_event = self._event(
                status="done",
                trace_id=trace_id,
                source="agent_runtime_v2",
                degraded=True,
                fallback_reason=runtime_error,
                data={
                    "answer": "当前请求处理超时，系统已降级。请缩短问题范围后重试。",
                    "citations": [],
                    "agent_used": "runtime_degraded",
                    "degraded": True,
                    "fallback_reason": runtime_error,
                },
            )
            await self._persist_event(state.tenant_id, trace_id, done_event.as_payload())
            yield done_event.as_payload()
        except Exception as exc:  # pragma: no cover - defensive path
            runtime_error = str(exc)
            if not first_event_sent:
                degraded_event = self._event(
                    status="thinking",
                    trace_id=trace_id,
                    source="agent_runtime_v2",
                    degraded=True,
                    fallback_reason="runtime_exception",
                    data={"msg": "运行时出现异常，正在切换到降级响应路径..."},
                )
                await self._persist_event(state.tenant_id, trace_id, degraded_event.as_payload())
                yield degraded_event.as_payload()
                first_event_sent = True
            else:
                error_event = self._event(
                    status="error",
                    trace_id=trace_id,
                    source="agent_runtime_v2",
                    degraded=True,
                    fallback_reason="runtime_exception",
                    data={"msg": "运行时出现异常，已触发降级路径。"},
                )
                await self._persist_event(state.tenant_id, trace_id, error_event.as_payload())
                yield error_event.as_payload()
            done_event = self._event(
                status="done",
                trace_id=trace_id,
                source="agent_runtime_v2",
                degraded=True,
                fallback_reason="runtime_exception",
                data={
                    "answer": "当前请求未能完成，已返回降级结果。",
                    "citations": [],
                    "agent_used": "runtime_degraded",
                    "degraded": True,
                    "fallback_reason": "runtime_exception",
                },
            )
            await self._persist_event(state.tenant_id, trace_id, done_event.as_payload())
            yield done_event.as_payload()
        finally:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_metrics(
                tenant_id=state.tenant_id,
                trace_id=trace_id,
                ttft_ms=0 if first_event_sent else elapsed_ms,
                completion_ms=elapsed_ms,
                fallback_rate=1 if runtime_error else 0,
                deny_rate=1 if deny_count > 0 else 0,
                retries=retry_count,
                tool_calls=tool_calls,
            )
            if runtime_error:
                await self.task_store.fail(task.task_id, runtime_error)
            else:
                await self.task_store.complete(task.task_id)

    async def _audit_tool_decision(self, decision: PermissionDecision, *, db) -> None:
        if db is None:
            return
        severity_map = {"allow": "low", "ask": "medium", "deny": "high"}
        await SecurityAuditService(self.redis, db).log_event(
            decision.tenant_id,
            "runtime_tool_decision",
            severity_map.get(decision.decision, "medium"),
            f"{decision.tool_name} -> {decision.decision} ({decision.reason})",
            user_id=decision.user_id,
            target=decision.tool_name,
            result=decision.decision,
            trace_id=decision.trace_id,
            metadata={
                "tool_name": decision.tool_name,
                "decision": decision.decision,
                "reason": decision.reason,
                "source": decision.source,
            },
        )

    def _event(
        self,
        *,
        status: str,
        trace_id: str,
        source: str,
        data: dict,
        degraded: bool = False,
        fallback_reason: str | None = None,
    ) -> RuntimeEvent:
        self._sequence += 1
        return RuntimeEvent(
            status=status,
            source=source,
            sequence_num=self._sequence,
            trace_id=trace_id,
            event_id=str(uuid.uuid4()),
            data=data,
            degraded=degraded,
            fallback_reason=fallback_reason,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    async def _persist_event(self, tenant_id: str, trace_id: str, payload: dict) -> None:
        if self.redis is None:
            return
        key = f"runtime:replay:{trace_id}"
        payload["tenant_id"] = tenant_id
        await self.redis.rpush(key, json.dumps(payload, ensure_ascii=False))
        await self.redis.expire(key, settings.runtime_event_replay_ttl_seconds)

    async def _record_metrics(
        self,
        *,
        tenant_id: str,
        trace_id: str,
        ttft_ms: int,
        completion_ms: int,
        fallback_rate: int,
        deny_rate: int,
        retries: int,
        tool_calls: int,
    ) -> None:
        if self.redis is None:
            return
        metrics = {
            "trace_id": trace_id,
            "ttft_ms": ttft_ms,
            "completion_ms": completion_ms,
            "fallback_rate": fallback_rate,
            "deny_rate": deny_rate,
            "retries": retries,
            "tool_calls": tool_calls,
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        }
        key = f"runtime:metrics:{tenant_id}"
        await self.redis.lpush(key, json.dumps(metrics, ensure_ascii=False))
        await self.redis.ltrim(key, 0, 999)
        await self.redis.expire(key, 14 * 24 * 3600)

    async def list_metrics(self, tenant_id: str, limit: int = 200) -> list[dict]:
        if self.redis is None:
            return []
        key = f"runtime:metrics:{tenant_id}"
        rows = await self.redis.lrange(key, 0, max(limit - 1, 0))
        items = []
        for row in rows:
            try:
                items.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        return items

    async def replay(self, trace_id: str) -> list[dict]:
        if self.redis is None:
            return []
        key = f"runtime:replay:{trace_id}"
        rows = await self.redis.lrange(key, 0, -1)
        items = []
        for row in rows:
            try:
                items.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        return items

    async def resume_from_checkpoint(self, request: RuntimeRequest, *, trace_id: str, db, current_user) -> AsyncIterator[dict]:
        from app.agent.runtime.langgraph_runner import LangGraphRuntimeRunner

        graph_runner = LangGraphRuntimeRunner(
            db=db,
            current_user=current_user,
            max_iterations=2,
        )
        async for event in graph_runner.astream_resume(
            trace_id,
            state_overrides={
                "query": request.query,
                "thread_id": request.thread_id,
                "session_id": request.thread_id,
                "search_type": request.search_type,
                "messages": request.history,
            },
        ):
            runtime_event = self._event(
                status=event.get("status", "streaming"),
                trace_id=trace_id,
                source="agent_runtime_v2_resume",
                degraded=bool(event.get("degraded", False)),
                fallback_reason=event.get("fallback_reason"),
                data={k: v for k, v in event.items() if k not in {"status", "trace_id"}},
            )
            await self._persist_event(str(getattr(current_user, "tenant_id", "default")), trace_id, runtime_event.as_payload())
            yield runtime_event.as_payload()
