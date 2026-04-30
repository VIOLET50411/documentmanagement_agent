import json

import pytest

from app.agent.runtime.task_store import TaskStore


class FakeRedis:
    def __init__(self, payload: dict):
        self.payload = payload

    async def get(self, _key: str):
        return json.dumps(self.payload, ensure_ascii=False)

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 200):
        return 0, ["runtime:task:task-1"]

    async def set(self, *_args, **_kwargs):
        return True

    async def zadd(self, *_args, **_kwargs):
        return True

    async def expire(self, *_args, **_kwargs):
        return True

    async def delete(self, *_args, **_kwargs):
        return True


@pytest.mark.asyncio
async def test_task_store_get_accepts_extended_payload_fields():
    store = TaskStore(
        FakeRedis(
            {
                "task_id": "task-1",
                "type": "evaluation",
                "status": "running",
                "description": "评估任务",
                "tenant_id": "tenant-1",
                "stage": "evaluating",
                "stage_payload": {"dataset_size": 1},
                "unexpected_field": "ignored",
            }
        )
    )

    record = await store.get("task-1")

    assert record is not None
    assert record.stage == "evaluating"
    assert record.stage_payload == {"dataset_size": 1}


@pytest.mark.asyncio
async def test_recover_stuck_running_handles_mixed_timezone_timestamps():
    store = TaskStore(
        FakeRedis(
            {
                "task_id": "task-1",
                "type": "evaluation",
                "status": "running",
                "description": "评估任务",
                "tenant_id": "tenant-1",
                "start_time": "2026-04-30T05:00:00",
                "updated_at": "2026-04-30T05:00:00+00:00",
            }
        )
    )

    recovered = await store.recover_stuck_running(timeout_seconds=1)

    assert recovered == 1
    record = await store.get("task-1")
    assert record is not None
    assert record.status == "failed"
    assert record.error == "recovered_timeout"