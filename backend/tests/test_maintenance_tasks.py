from __future__ import annotations

import json
import pytest

from app.maintenance import tasks


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple] = []
        self.closed = False

    async def execute(self, *args):
        self.calls.append(args)

    async def close(self):
        self.closed = True


class _FakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.expirations: dict[str, int] = {}
        self.closed = False

    async def lpush(self, key: str, value: str):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key: str, start: int, end: int):
        rows = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        self.lists[key] = rows[start:stop]
        return True

    async def expire(self, key: str, ttl: int):
        self.expirations[key] = ttl
        return True

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_write_audit_writes_runtime_alert_to_redis(monkeypatch):
    fake_conn = _FakeConn()
    fake_redis = _FakeRedis()

    async def fake_connect(_dsn):
        return fake_conn

    monkeypatch.setattr(tasks.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(tasks.redis.asyncio, "from_url", lambda *args, **kwargs: fake_redis)

    await tasks._write_audit(
        tenant_id="tenant-1",
        action="runtime_maintenance_alert",
        severity="medium",
        result="warning",
        message="runtime maintenance alert: repaired_ttl_keys=88",
        metadata={"stats": {"repaired_replay_ttl": 88}},
    )

    assert fake_conn.closed is True
    assert fake_redis.closed is True
    assert "security_audit:tenant-1" in fake_redis.lists
    assert "security_alerts:tenant-1" in fake_redis.lists
    payload = json.loads(fake_redis.lists["security_alerts:tenant-1"][0])
    assert payload["action"] == "runtime_maintenance_alert"
    assert payload["result"] == "warning"
    assert payload["severity"] == "medium"


@pytest.mark.asyncio
async def test_write_audit_does_not_create_alert_for_low_ok(monkeypatch):
    fake_conn = _FakeConn()
    fake_redis = _FakeRedis()

    async def fake_connect(_dsn):
        return fake_conn

    monkeypatch.setattr(tasks.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(tasks.redis.asyncio, "from_url", lambda *args, **kwargs: fake_redis)

    await tasks._write_audit(
        tenant_id="tenant-2",
        action="runtime_maintenance",
        severity="low",
        result="ok",
        message="runtime maintenance completed",
        metadata={"stats": {"repaired_replay_ttl": 1}},
    )

    assert "security_audit:tenant-2" in fake_redis.lists
    assert "security_alerts:tenant-2" not in fake_redis.lists


def test_runtime_maintenance_job_writes_security_policy_alert(monkeypatch):
    calls = []

    monkeypatch.setattr(tasks, "_list_runtime_tenants", lambda: ["tenant-1"])

    async def fake_run_runtime_maintenance(cleanup_empty=True):
        return {
            "scanned_replay_keys": 1,
            "repaired_replay_ttl": 0,
            "repaired_task_ttl": 0,
            "repaired_task_index_ttl": 0,
            "removed_empty_replay": 0,
            "recovered_stuck_tasks": 0,
        }

    monkeypatch.setattr(tasks, "_run_runtime_maintenance", fake_run_runtime_maintenance)
    monkeypatch.setattr(
        tasks,
        "_evaluate_security_policy",
        lambda: {
            "profile": "financial",
            "compliant": False,
            "blocking": True,
            "failed_controls": [{"id": "guardrails_fail_closed", "message": "Guardrails fail-closed"}],
            "recommended_actions": ["开启 Guardrails fail-closed。"],
            "auto_action": "block_high_risk_operations",
        },
    )
    monkeypatch.setattr(tasks, "_build_alert", lambda _stats: {"triggered": False, "reasons": []})

    async def fake_write_audit(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(tasks, "_write_audit", fake_write_audit)

    result = tasks.runtime_maintenance_job.run(cleanup_empty=True)

    assert result["ok"] is True
    assert result["security_policy"]["compliant"] is False
    assert len(calls) == 2
    assert calls[0]["metadata"]["security_policy"]["profile"] == "financial"
    assert calls[1]["action"] == "security_policy_alert"
    assert calls[1]["severity"] == "critical"
    assert calls[1]["result"] == "blocked"
    assert "guardrails_fail_closed" in calls[1]["message"]
    assert calls[1]["metadata"]["auto_action"] == "block_high_risk_operations"


def test_evaluate_security_policy_falls_back_on_error(monkeypatch):
    class BrokenPolicyService:
        def evaluate(self):
            raise RuntimeError("sidecar down")

    monkeypatch.setattr("app.services.security_policy_service.SecurityPolicyService", BrokenPolicyService)

    result = tasks._evaluate_security_policy()

    assert result["compliant"] is False
    assert result["blocking"] is True
    assert result["status"] == "blocked"
    assert result["failed_controls"][0]["id"] == "security_policy_evaluation_error"
    assert "sidecar down" in result["error"]


def test_run_evaluation_job_success(monkeypatch):
    calls: list[dict] = []

    async def fake_run_async(**kwargs):
        calls.append(kwargs)
        return {"dataset_size": 5, "gate": {"passed": True}}

    monkeypatch.setattr(tasks, "_run_evaluation_job_async", fake_run_async)

    tasks.run_evaluation_job.push_request(id="eval-task-1")
    try:
        result = tasks.run_evaluation_job.run("tenant-1", sample_limit=5, actor_id="admin-1")
    finally:
        tasks.run_evaluation_job.pop_request()

    assert result["ok"] is True
    assert result["task_id"] == "eval-task-1"
    assert result["dataset_size"] == 5
    assert calls[0]["tenant_id"] == "tenant-1"
    assert calls[0]["sample_limit"] == 5
    assert calls[0]["actor_id"] == "admin-1"


def test_run_evaluation_job_failure(monkeypatch):
    async def fake_run_async(**kwargs):
        raise RuntimeError("evaluation boom")

    audit_calls: list[dict] = []
    runtime_updates: list[dict] = []

    async def fake_write_audit(**kwargs):
        audit_calls.append(kwargs)

    def fake_upsert(**kwargs):
        runtime_updates.append(kwargs)

    monkeypatch.setattr(tasks, "_run_evaluation_job_async", fake_run_async)
    monkeypatch.setattr(tasks, "_write_audit", fake_write_audit)
    monkeypatch.setattr(tasks, "_upsert_runtime_task_record", fake_upsert)

    tasks.run_evaluation_job.push_request(id="eval-task-2")
    try:
        result = tasks.run_evaluation_job.run("tenant-2", sample_limit=3, actor_id="admin-2")
    finally:
        tasks.run_evaluation_job.pop_request()

    assert result["ok"] is False
    assert result["task_id"] == "eval-task-2"
    assert "evaluation boom" in result["error"]
    assert runtime_updates[-1]["status"] == "failed"
    assert audit_calls[0]["action"] == "evaluation_run"
    assert audit_calls[0]["result"] == "error"
