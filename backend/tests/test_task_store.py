import json

import pytest

from app.agent.runtime.task_store import TaskStore


class FakeRedis:
    def __init__(self, payload: dict):
        self.payload = payload

    async def get(self, _key: str):
        return json.dumps(self.payload, ensure_ascii=False)


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
