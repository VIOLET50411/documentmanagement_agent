from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.runtime_checkpoint_service import RuntimeCheckpointService


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class FakeDB:
    def __init__(self, items):
        self.items = items

    async def execute(self, _query):
        return FakeResult(self.items)


@pytest.mark.asyncio
async def test_runtime_checkpoint_service_summarizes_latest_session_state(monkeypatch):
    monkeypatch.setattr(
        "app.services.runtime_checkpoint_service.native_checkpoint_support_status",
        lambda: {
            "enabled": True,
            "available": True,
            "compatible": True,
            "reason": "ok",
            "versions": {"langgraph": "0.5.0"},
        },
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    items = [
        SimpleNamespace(
            session_id='s-1',
            tenant_id='t-1',
            trace_id='trace-old',
            node_name='retriever',
            iteration=0,
            created_at=now - timedelta(minutes=2),
            payload_json='{"intent":"qa","rewritten_query":"旧查询","warnings":[],"answer_preview":""}',
        ),
        SimpleNamespace(
            session_id='s-1',
            tenant_id='t-1',
            trace_id='trace-new',
            node_name='critic',
            iteration=1,
            created_at=now,
            payload_json='{"intent":"qa","rewritten_query":"新查询","warnings":["retrieval_insufficient"],"answer_preview":"摘要"}',
        ),
        SimpleNamespace(
            session_id='s-2',
            tenant_id='t-1',
            trace_id='trace-2',
            node_name='generator',
            iteration=0,
            created_at=now - timedelta(minutes=1),
            payload_json='{"intent":"summarize","rewritten_query":"摘要查询","warnings":[]}',
        ),
    ]

    rows = await RuntimeCheckpointService(FakeDB(items)).summarize_sessions('t-1', limit=10)

    assert len(rows) == 2
    assert rows[0]['session_id'] == 's-1'
    assert rows[0]['trace_id'] == 'trace-new'
    assert rows[0]['latest_node_name'] == 'critic'
    assert rows[0]['checkpoint_count'] == 2
    assert rows[0]['rewritten_query'] == '新查询'
    assert rows[0]['warnings'] == ['retrieval_insufficient']
    assert rows[0]['resume_strategy'] == 'native'
    assert rows[0]['native_checkpoint_enabled'] is True
    assert rows[0]['native_checkpoint_available'] is True
    assert rows[0]['native_checkpoint_compatible'] is True
    assert rows[0]['native_checkpoint_reason'] == 'ok'


@pytest.mark.asyncio
async def test_runtime_checkpoint_service_marks_terminal_sessions(monkeypatch):
    monkeypatch.setattr(
        "app.services.runtime_checkpoint_service.native_checkpoint_support_status",
        lambda: {
            "enabled": True,
            "available": False,
            "compatible": False,
            "reason": "langgraph_checkpoint_postgres_requires_langgraph_gte_0_5",
            "versions": {"langgraph": "0.2.34"},
        },
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    items = [
        SimpleNamespace(
            session_id='s-3',
            tenant_id='t-1',
            trace_id='trace-terminal',
            node_name='done',
            iteration=1,
            created_at=now,
            payload_json='{"intent":"qa","rewritten_query":"完成查询","warnings":[],"answer_preview":"已完成"}',
        )
    ]

    rows = await RuntimeCheckpointService(FakeDB(items)).summarize_sessions('t-1', limit=10)

    assert rows[0]['resumable'] is False
    assert rows[0]['resume_strategy'] == 'terminal'
    assert rows[0]['native_checkpoint_enabled'] is True
    assert rows[0]['native_checkpoint_available'] is False
    assert rows[0]['native_checkpoint_compatible'] is False
    assert rows[0]['native_checkpoint_reason'] == 'langgraph_checkpoint_postgres_requires_langgraph_gte_0_5'
