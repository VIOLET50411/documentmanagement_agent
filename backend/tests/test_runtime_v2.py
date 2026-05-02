from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.agent.runtime import AgentRuntime, RuntimeRequest
from app.agent.runtime.langgraph_runner import LangGraphRuntimeRunner
from app.agent.runtime.permission_gate import PermissionGate
from app.agent.runtime.tool_registry import ToolSpec


@pytest.mark.asyncio
async def test_runtime_v2_emits_protocol_fields(monkeypatch):
    class DummyGraphRunner:
        def __init__(self, **_kwargs):
            pass

        async def astream(self, _state):
            yield {"status": "thinking", "msg": "正在处理"}
            yield {"status": "done", "answer": "ok", "citations": [], "agent_used": "dummy"}

    monkeypatch.setattr("app.agent.runtime.langgraph_runner.LangGraphRuntimeRunner", DummyGraphRunner)
    runtime = AgentRuntime(None)
    request = RuntimeRequest(
        query="test",
        thread_id="thread-1",
        search_type="hybrid",
        user_context={"user_id": "u1", "tenant_id": "t1", "role": "ADMIN"},
        history=[],
    )

    user = type("User", (), {"id": "u1", "tenant_id": "t1", "role": "ADMIN"})()
    events = []
    async for event in runtime.run(request, db=None, current_user=user):
        events.append(event)

    assert events
    assert all("event_id" in item for item in events)
    assert all("sequence_num" in item for item in events)
    assert all("trace_id" in item for item in events)
    assert events[-1]["status"] == "done"


@pytest.mark.asyncio
async def test_runtime_v2_resume_from_checkpoint_emits_events(monkeypatch):
    class DummyGraphRunner:
        def __init__(self, **_kwargs):
            pass

        async def astream_resume(self, _trace_id, *, state_overrides=None):
            assert state_overrides["query"] == "resume me"
            yield {"status": "reading", "msg": "已恢复", "resume_strategy": "checkpoint_load"}
            yield {"status": "done", "answer": "resumed", "citations": [], "agent_used": "dummy_resume", "resume_strategy": "manual"}

    monkeypatch.setattr("app.agent.runtime.langgraph_runner.LangGraphRuntimeRunner", DummyGraphRunner)
    runtime = AgentRuntime(None)
    request = RuntimeRequest(
        query="resume me",
        thread_id="thread-1",
        search_type="hybrid",
        user_context={"user_id": "u1", "tenant_id": "t1", "role": "ADMIN"},
        history=[],
    )

    user = type("User", (), {"id": "u1", "tenant_id": "t1", "role": "ADMIN"})()
    events = []
    async for event in runtime.resume_from_checkpoint(request, trace_id="trace-resume", db=None, current_user=user):
        events.append(event)

    assert events
    assert events[0]["status"] == "reading"
    assert events[0]["resume_strategy"] == "checkpoint_load"
    assert events[-1]["status"] == "done"
    assert events[-1]["answer"] == "resumed"
    assert events[-1]["resume_strategy"] == "manual"
    assert all(item["trace_id"] == "trace-resume" for item in events)


@pytest.mark.asyncio
async def test_runtime_v2_exception_still_emits_status_before_done(monkeypatch):
    class DummyGraphRunner:
        def __init__(self, **_kwargs):
            pass

        async def astream(self, _state):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    monkeypatch.setattr("app.agent.runtime.langgraph_runner.LangGraphRuntimeRunner", DummyGraphRunner)
    runtime = AgentRuntime(None)
    request = RuntimeRequest(
        query="test",
        thread_id="thread-1",
        search_type="hybrid",
        user_context={"user_id": "u1", "tenant_id": "t1", "role": "ADMIN"},
        history=[],
    )

    user = type("User", (), {"id": "u1", "tenant_id": "t1", "role": "ADMIN"})()
    events = []
    async for event in runtime.run(request, db=None, current_user=user):
        events.append(event)

    assert events[0]["status"] == "thinking"
    assert events[0]["degraded"] is True
    assert events[-1]["status"] == "done"
    assert events[-1]["fallback_reason"] == "runtime_exception"


@pytest.mark.asyncio
async def test_langgraph_runner_prefers_native_checkpoint_resume(monkeypatch):
    user = type("User", (), {"id": "u1", "tenant_id": "t1", "role": "ADMIN"})()
    runner = LangGraphRuntimeRunner(db=None, current_user=user)

    checkpoint = SimpleNamespace(node_name="retriever")

    class FakeCheckpointStore:
        async def latest_for_trace(self, trace_id):
            assert trace_id == "trace-native"
            return checkpoint

        def deserialize_payload(self, _checkpoint):
            return {
                "trace_id": "trace-native",
                "thread_id": "thread-1",
                "answer": "checkpoint answer",
                "citations": [],
                "degraded": False,
            }

    runner.checkpoints = FakeCheckpointStore()

    @asynccontextmanager
    async def fake_native_checkpointer():
        yield object()

    async def fake_run_until_complete(graph, initial_input, *, config):
        assert initial_input is None
        assert config["configurable"]["thread_id"] == "trace-native"
        yield {
            "state": {"trace_id": "trace-native", "answer": "native resumed answer", "citations": [], "degraded": False},
            "payload": {"status": "streaming", "msg": "正在从原生检查点继续执行"},
        }

    async def fake_safe_get_state(graph, config):
        return SimpleNamespace(values={"trace_id": "trace-native", "answer": "before resume"}, next=("generator",))

    monkeypatch.setattr(runner, "_native_checkpointer", fake_native_checkpointer)
    monkeypatch.setattr(runner, "_build_graph", lambda checkpointer=None: object())
    monkeypatch.setattr(runner, "_safe_get_state", fake_safe_get_state)
    monkeypatch.setattr(runner, "_run_until_complete", fake_run_until_complete)

    events = []
    async for event in runner.astream_resume("trace-native", state_overrides={"query": "继续"}):
        events.append(event)

    assert events[0]["status"] == "reading"
    assert events[0]["resume_strategy"] == "checkpoint_load"
    assert events[1]["status"] == "streaming"
    assert events[1]["resume_strategy"] == "native"
    assert events[-1]["status"] == "done"
    assert events[-1]["answer"] == "native resumed answer"
    assert events[-1]["agent_used"] == "langgraph_runtime_resume"
    assert events[-1]["resume_strategy"] == "native"


def test_langgraph_runner_checkpoint_payload_persists_degraded_state():
    user = type("User", (), {"id": "u1", "tenant_id": "t1", "role": "ADMIN"})()
    runner = LangGraphRuntimeRunner(db=None, current_user=user)

    payload = runner._checkpoint_payload(
        {
            "query": "测试查询",
            "rewritten_query": "改写后的查询",
            "intent": "qa",
            "iteration": 2,
            "thread_id": "thread-1",
            "session_id": "thread-1",
            "selected_agent": "summary",
            "agent_used": "summary",
            "retrieval_sufficient": False,
            "critic_approved": False,
            "degraded": True,
            "fallback_reason": "retrieval_insufficient",
            "warnings": ["retrieval_insufficient"],
            "citations": [{"doc_id": "doc-1"}],
            "answer": "降级回答",
        }
    )

    assert payload["degraded"] is True
    assert payload["fallback_reason"] == "retrieval_insufficient"
    assert payload["warnings"] == ["retrieval_insufficient"]
    assert payload["answer_preview"] == "降级回答"


@pytest.mark.asyncio
async def test_permission_gate_handles_allow_ask_and_deny():
    gate = PermissionGate(None)

    allow = await gate.evaluate(
        tool=ToolSpec(name="retrieval.search", description="search", risk_level="low"),
        user_context={"user_id": "u1", "tenant_id": "t1", "role": "EMPLOYEE"},
        trace_id="trace-1",
    )
    ask = await gate.evaluate(
        tool=ToolSpec(name="dangerous.tool", description="danger", risk_level="high"),
        user_context={"user_id": "u1", "tenant_id": "t1", "role": "EMPLOYEE"},
        trace_id="trace-2",
    )
    deny = await gate.evaluate(tool=None, user_context={"user_id": "u1", "tenant_id": "t1"}, trace_id="trace-3")

    assert allow.decision == "allow"
    assert ask.decision == "ask"
    assert deny.decision == "deny"
