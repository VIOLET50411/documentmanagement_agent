from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

TERMINAL_STATUSES = {"completed", "failed", "killed"}


@dataclass
class TaskRecord:
    task_id: str
    type: str
    status: str
    description: str = ""
    tenant_id: str | None = None
    session_id: str | None = None
    tool_use_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    output_offset: int = 0
    retries: int = 0
    notified: bool = False
    trace_id: str | None = None
    stage: str | None = None
    stage_payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    updated_at: str | None = None


class TaskStore:
    def __init__(self, redis=None, retention_seconds: int = 3600):
        self.redis = redis
        self.retention_seconds = retention_seconds
        self._memory: dict[str, TaskRecord] = {}

    def _task_key(self, task_id: str) -> str:
        return f"runtime:task:{task_id}"

    def _tenant_index(self, tenant_id: str) -> str:
        return f"runtime:tasks:{tenant_id}"

    async def register(self, record: TaskRecord | None = None, **kwargs) -> TaskRecord:
        if record is None:
            now = datetime.now(timezone.utc).isoformat()
            allowed = set(TaskRecord.__dataclass_fields__.keys())
            payload = {
                "task_id": kwargs.get("task_id") or kwargs.get("id") or kwargs.get("trace_id") or now,
                "type": kwargs.get("task_type") or kwargs.get("type") or "generic",
                "status": kwargs.get("status") or "pending",
                "description": kwargs.get("description") or "",
                "tenant_id": kwargs.get("tenant_id"),
                "session_id": kwargs.get("session_id"),
                "tool_use_id": kwargs.get("tool_use_id"),
                "start_time": kwargs.get("start_time") or now,
                "end_time": kwargs.get("end_time"),
                "output_offset": kwargs.get("output_offset", 0),
                "retries": kwargs.get("retries", 0),
                "notified": kwargs.get("notified", False),
                "trace_id": kwargs.get("trace_id"),
                "stage": kwargs.get("stage"),
                "stage_payload": kwargs.get("stage_payload") or {},
                "result": kwargs.get("result"),
                "error": kwargs.get("error"),
                "updated_at": kwargs.get("updated_at") or now,
            }
            record = TaskRecord(**{key: value for key, value in payload.items() if key in allowed})
        await self._save(record)
        return record

    async def update(self, task_id: str, **changes) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        for key, value in changes.items():
            if hasattr(record, key):
                setattr(record, key, value)
        record.updated_at = datetime.now(timezone.utc).isoformat()
        await self._save(record)
        return record

    async def complete(self, task_id: str, result: dict[str, Any] | None = None) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if record.status == "completed":
            return record
        record.status = "completed"
        record.end_time = datetime.now(timezone.utc).isoformat()
        record.updated_at = record.end_time
        record.result = result
        await self._save(record, terminal=True)
        return record

    async def fail(self, task_id: str, error: str, **extra) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if record.status == "failed":
            return record
        record.status = "failed"
        record.error = error
        record.end_time = datetime.now(timezone.utc).isoformat()
        record.updated_at = record.end_time
        for key, value in extra.items():
            if hasattr(record, key):
                setattr(record, key, value)
        await self._save(record, terminal=True)
        return record

    async def kill(self, task_id: str) -> TaskRecord | None:
        record = await self.get(task_id)
        if record is None:
            return None
        if record.status == "killed":
            return record
        record.status = "killed"
        record.end_time = datetime.now(timezone.utc).isoformat()
        record.updated_at = record.end_time
        await self._save(record, terminal=True)
        return record

    async def evict(self, task_id: str) -> None:
        self._memory.pop(task_id, None)
        if self.redis is not None:
            await self.redis.delete(self._task_key(task_id))

    async def list(self, tenant_id: str | None = None) -> list[TaskRecord]:
        items = list(self._memory.values())
        if self.redis is not None and tenant_id:
            task_ids = await self.redis.zrevrange(self._tenant_index(tenant_id), 0, -1)
            for task_id in task_ids or []:
                if task_id in self._memory:
                    continue
                raw = await self.redis.get(self._task_key(task_id))
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                    self._memory[task_id] = TaskRecord(**payload)
                except json.JSONDecodeError:
                    continue
        items = list(self._memory.values())
        if tenant_id:
            items = [item for item in items if item.tenant_id == tenant_id]
        return items

    async def recover_stuck_running(self, timeout_seconds: int) -> int:
        now = datetime.now(timezone.utc)
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
            reference_time = item.updated_at or item.start_time
            started_at = self._parse_datetime(reference_time, fallback=now)
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

    def _parse_datetime(self, value: str | None, *, fallback: datetime) -> datetime:
        if not value:
            return fallback
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return fallback
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
