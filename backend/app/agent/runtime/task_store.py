"""Unified runtime task state store."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


TERMINAL_STATUSES = {"completed", "failed", "killed"}
TOP_LEVEL_STATUSES = {"pending", "running", "completed", "failed", "killed"}


@dataclass(slots=True)
class TaskRecord:
    """Standard task record."""

    task_id: str
    type: str
    status: str
    description: str
    tool_use_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    output_offset: int = 0
    retries: int = 0
    notified: bool = False
    trace_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    stage: str | None = None
    stage_payload: dict[str, Any] | None = None
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None).isoformat())


class TaskStore:
    """Task store with Redis-first persistence and in-memory fallback."""

    def __init__(self, redis_client=None, retention_seconds: int = 3600):
        self.redis = redis_client
        self.retention_seconds = retention_seconds
        self._memory: dict[str, TaskRecord] = {}

    @staticmethod
    def _task_key(task_id: str) -> str:
        return f"runtime:task:{task_id}"

    @staticmethod
    def _tenant_index(tenant_id: str) -> str:
        return f"runtime:tasks:{tenant_id}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    async def register(self, *, task_type: str, description: str, tenant_id: str, trace_id: str | None = None, session_id: str | None = None) -> TaskRecord:
        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            type=task_type,
            status="pending",
            description=description,
            trace_id=trace_id,
            tenant_id=tenant_id,
            session_id=session_id,
            start_time=self._now(),
            updated_at=self._now(),
        )
        await self._save(record)
        return record

    async def update(self, task_id: str, **fields: Any) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if "status" in fields and fields["status"] not in TOP_LEVEL_STATUSES:
            fields["status"] = "failed"
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = self._now()
        await self._save(record)
        return record

    async def complete(self, task_id: str, *, delta: int = 0) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if record.status in TERMINAL_STATUSES:
            return record
        record.status = "completed"
        record.output_offset = max(record.output_offset + max(delta, 0), 0)
        record.end_time = self._now()
        record.updated_at = self._now()
        await self._save(record, terminal=True)
        return record

    async def fail(self, task_id: str, error: str, *, recovered_timeout: bool = False) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if record.status in TERMINAL_STATUSES:
            return record
        record.status = "failed"
        record.error = "recovered_timeout" if recovered_timeout else error
        record.end_time = self._now()
        record.updated_at = self._now()
        await self._save(record, terminal=True)
        return record

    async def kill(self, task_id: str) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if record.status in TERMINAL_STATUSES:
            return record
        record.status = "killed"
        record.end_time = self._now()
        record.updated_at = self._now()
        await self._save(record, terminal=True)
        return record

    async def evict(self, task_id: str) -> None:
        record = await self.get(task_id)
        if record is None:
            return
        self._memory.pop(task_id, None)
        if self.redis is not None:
            await self.redis.delete(self._task_key(task_id))
            if record.tenant_id:
                await self.redis.zrem(self._tenant_index(record.tenant_id), task_id)

    async def list_tasks(self, tenant_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        if self.redis is None:
            values = [asdict(item) for item in self._memory.values() if item.tenant_id == tenant_id]
            values.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
            return values[offset : offset + limit]

        index_key = self._tenant_index(tenant_id)
        task_ids = await self.redis.zrevrange(index_key, offset, offset + max(limit - 1, 0))
        items: list[dict[str, Any]] = []
        for task_id in task_ids:
            raw = await self.redis.get(self._task_key(task_id))
            if raw:
                try:
                    items.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        return items

    async def recover_stuck_running(self, timeout_seconds: int) -> int:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        recovered = 0
        items = list(self._memory.values())
        if self.redis is not None:
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor=cursor, match="runtime:task:*", count=200)
                for key in keys or []:
                    raw = await self.redis.get(key)
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    task_id = payload.get("task_id")
                    if task_id and task_id not in self._memory:
                        try:
                            self._memory[task_id] = TaskRecord(**payload)
                        except TypeError:
                            continue
                if cursor == 0:
                    break
            items = list(self._memory.values())
        for item in items:
            if item.status != "running":
                continue
            started_at = datetime.fromisoformat(item.start_time) if item.start_time else now
            elapsed = (now - started_at).total_seconds()
            if elapsed > timeout_seconds:
                await self.fail(item.task_id, "recovered_timeout", recovered_timeout=True)
                recovered += 1
        return recovered

    async def get(self, task_id: str) -> TaskRecord | None:
        if task_id in self._memory:
            return self._memory[task_id]
        if self.redis is None:
            return None
        raw = await self.redis.get(self._task_key(task_id))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        allowed = set(TaskRecord.__dataclass_fields__.keys())
        payload = {key: value for key, value in payload.items() if key in allowed}
        record = TaskRecord(**payload)
        self._memory[task_id] = record
        return record

    async def _save(self, record: TaskRecord, terminal: bool = False) -> None:
        self._memory[record.task_id] = record
        if self.redis is None:
            return
        key = self._task_key(record.task_id)
        payload = json.dumps(asdict(record), ensure_ascii=False)
        await self.redis.set(key, payload, ex=self.retention_seconds)
        if record.tenant_id:
            now_ts = datetime.now(timezone.utc).timestamp()
            await self.redis.zadd(self._tenant_index(record.tenant_id), {record.task_id: now_ts})
            await self.redis.expire(self._tenant_index(record.tenant_id), self.retention_seconds)
        if terminal:
            await self.redis.expire(key, self.retention_seconds)
