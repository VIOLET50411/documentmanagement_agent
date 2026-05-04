from __future__ import annotations

from types import SimpleNamespace

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from app.config import settings
from app.training import tasks as training_tasks


def test_run_training_job_uses_training_specific_time_limits():
    assert training_tasks.run_training_job.soft_time_limit == settings.llm_training_task_soft_time_limit_seconds
    assert training_tasks.run_training_job.time_limit == settings.llm_training_task_time_limit_seconds


def test_run_training_job_marks_failed_on_soft_timeout(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_run_training_job_async(*, training_job_id: str, runtime_task_id: str):
        raise SoftTimeLimitExceeded()

    async def fake_mark_job_failure_async(*, training_job_id: str, runtime_task_id: str, error: str, terminal_status: str, **kwargs):
        captured["training_job_id"] = training_job_id
        captured["runtime_task_id"] = runtime_task_id
        captured["error"] = error
        captured["terminal_status"] = terminal_status
        return {"ok": False, "job_id": training_job_id, "error": error}

    monkeypatch.setattr(training_tasks, "_run_training_job_async", fake_run_training_job_async)
    monkeypatch.setattr(training_tasks, "_mark_job_failure_async", fake_mark_job_failure_async)
    training_tasks.run_training_job.push_request(id="runtime-task-1")
    try:
        result = training_tasks.run_training_job.run("job-1")
    finally:
        training_tasks.run_training_job.pop_request()

    assert result["ok"] is False
    assert captured["training_job_id"] == "job-1"
    assert captured["runtime_task_id"] == "runtime-task-1"
    assert captured["terminal_status"] == "failed"
    assert bytes("\\u8d85\\u65f6", "utf-8").decode("unicode_escape") in captured["error"]


@pytest.mark.asyncio
async def test_upsert_runtime_task_ignores_redis_failures(monkeypatch):
    class FailingRedisClient:
        async def get(self, key):
            raise RuntimeError("redis unavailable")

        async def aclose(self):
            return None

    monkeypatch.setattr(training_tasks.redis.asyncio, "from_url", lambda *args, **kwargs: FailingRedisClient())

    await training_tasks._upsert_runtime_task(
        runtime_task_id="runtime-task-2",
        tenant_id="tenant-1",
        training_job_id="job-2",
        status="running",
        stage="executing",
        payload={"heartbeat_at": "2026-04-30T00:00:00"},
    )


@pytest.mark.asyncio
async def test_evaluate_deployment_gate_records_blocked_gate(monkeypatch):
    recorded: dict[str, object] = {}
    audited: list[dict[str, object]] = []

    class FakeEvaluationService:
        async def assess_deployment_readiness(self, tenant_id: str, *, max_age_hours: int | None = None):
            assert tenant_id == "tenant-1"
            assert max_age_hours == settings.llm_training_eval_max_age_hours
            return {"ready": False, "reason": "evaluation_gate_failed", "message": bytes("\\u8d28\\u91cf\\u95e8\\u7981\\u672a\\u901a\\u8fc7", "utf-8").decode("unicode_escape")}

    class FakeTrainingService:
        async def record_deployment_gate_result(self, *, tenant_id: str, model_id: str, payload: dict):
            recorded["tenant_id"] = tenant_id
            recorded["model_id"] = model_id
            recorded["payload"] = payload
            return payload

    async def fake_audit_training_event(_audit, **kwargs):
        audited.append(kwargs)

    monkeypatch.setattr(training_tasks, "_audit_training_event", fake_audit_training_event)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", True)
    monkeypatch.setattr(settings, "llm_training_eval_max_age_hours", 12)

    gate = await training_tasks._evaluate_deployment_gate(
        evaluation_service=FakeEvaluationService(),
        training_service=FakeTrainingService(),
        audit=SimpleNamespace(),
        job=SimpleNamespace(id="job-1", tenant_id="tenant-1", created_by="admin-1"),
        model=SimpleNamespace(id="model-1"),
        runtime_task_id="trace-1",
    )

    assert gate["ready"] is False
    assert recorded["tenant_id"] == "tenant-1"
    assert recorded["model_id"] == "model-1"
    assert audited[0]["event_type"] == "llm_model_deployment_gate"
    assert audited[0]["result"] == "warning"


@pytest.mark.asyncio
async def test_evaluate_deployment_gate_skips_check_when_disabled(monkeypatch):
    class UnexpectedEvaluationService:
        async def assess_deployment_readiness(self, tenant_id: str, *, max_age_hours: int | None = None):
            raise AssertionError("should not evaluate when gate is disabled")

    recorded: list[dict[str, object]] = []

    class FakeTrainingService:
        async def record_deployment_gate_result(self, *, tenant_id: str, model_id: str, payload: dict):
            recorded.append(payload)
            return payload

    async def fake_audit_training_event(_audit, **kwargs):
        return None

    monkeypatch.setattr(training_tasks, "_audit_training_event", fake_audit_training_event)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", False)

    gate = await training_tasks._evaluate_deployment_gate(
        evaluation_service=UnexpectedEvaluationService(),
        training_service=FakeTrainingService(),
        audit=SimpleNamespace(),
        job=SimpleNamespace(id="job-1", tenant_id="tenant-1", created_by="admin-1"),
        model=SimpleNamespace(id="model-1"),
        runtime_task_id="trace-1",
    )

    assert gate["ready"] is True
    assert gate["reason"] == "evaluation_gate_disabled"
    assert recorded[0]["reason"] == "evaluation_gate_disabled"


@pytest.mark.asyncio
async def test_auto_publish_and_activation_verifies_before_activate(monkeypatch):
    order: list[str] = []
    persisted_stages: list[str] = []
    runtime_stages: list[str] = []

    class FakeService:
        async def publish_model_artifact(self, *, tenant_id: str, model_id: str):
            order.append("publish")
            return {"ok": True, "publish_ready": True, "published": True, "serving_model_name": "tenant-model", "reason": "published"}

        async def verify_model_serving(self, *, tenant_id: str, model_id: str):
            order.append("verify")
            return {"ok": True, "reason": "verified"}

        async def activate_model(self, *, tenant_id: str, model_id: str, actor_id: str | None = None):
            order.append("activate")
            return SimpleNamespace(id=model_id)

    async def fake_persist_job_stage(service, db, training_job_id: str, *, status: str, stage: str, **kwargs):
        persisted_stages.append(stage)

    async def fake_upsert_runtime_task(*, stage: str, **kwargs):
        runtime_stages.append(stage)

    async def fake_audit_training_event(_audit, **kwargs):
        return None

    monkeypatch.setattr(training_tasks, "_persist_job_stage", fake_persist_job_stage)
    monkeypatch.setattr(training_tasks, "_upsert_runtime_task", fake_upsert_runtime_task)
    monkeypatch.setattr(training_tasks, "_audit_training_event", fake_audit_training_event)
    monkeypatch.setattr(settings, "llm_training_auto_activate", True)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", False)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", False)
    monkeypatch.setattr(settings, "llm_training_deploy_verify_enabled", True)

    publish_result, deployment_verification, auto_activated = await training_tasks._handle_auto_publish_and_activation(
        service=FakeService(),
        db=SimpleNamespace(),
        audit=SimpleNamespace(),
        job=SimpleNamespace(id="job-1", tenant_id="tenant-1", created_by="admin-1", activate_on_success=True),
        model=SimpleNamespace(id="model-1", model_name="tenant-model"),
        validated_result={"executor_metadata": {"publish_ready": True}, "serving_model_name": "tenant-model"},
        evaluation_gate={"ready": True},
        runtime_task_id="task-1",
        training_job_id="job-1",
    )

    assert publish_result["published"] is True
    assert deployment_verification == {"ok": True, "reason": "verified"}
    assert auto_activated is True
    assert order == ["publish", "verify", "activate"]
    assert persisted_stages == ["verifying", "deploying"]
    assert runtime_stages == ["verifying", "deploying"]


@pytest.mark.asyncio
async def test_auto_publish_and_activation_blocks_cutover_when_verify_fails(monkeypatch):
    order: list[str] = []

    class FakeService:
        async def publish_model_artifact(self, *, tenant_id: str, model_id: str):
            order.append("publish")
            return {"ok": True, "publish_ready": True, "published": True, "serving_model_name": "tenant-model", "reason": "published"}

        async def verify_model_serving(self, *, tenant_id: str, model_id: str):
            order.append("verify")
            return {"ok": False, "reason": "all_health_checks_failed"}

        async def activate_model(self, *, tenant_id: str, model_id: str, actor_id: str | None = None):
            order.append("activate")
            raise AssertionError("activate_model should not run when verification fails")

    async def fake_persist_job_stage(*args, **kwargs):
        return None

    async def fake_upsert_runtime_task(**kwargs):
        return None

    async def fake_audit_training_event(_audit, **kwargs):
        return None

    monkeypatch.setattr(training_tasks, "_persist_job_stage", fake_persist_job_stage)
    monkeypatch.setattr(training_tasks, "_upsert_runtime_task", fake_upsert_runtime_task)
    monkeypatch.setattr(training_tasks, "_audit_training_event", fake_audit_training_event)
    monkeypatch.setattr(settings, "llm_training_auto_activate", True)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", False)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", False)
    monkeypatch.setattr(settings, "llm_training_deploy_verify_enabled", True)

    with pytest.raises(RuntimeError, match="部署校验失败"):
        await training_tasks._handle_auto_publish_and_activation(
            service=FakeService(),
            db=SimpleNamespace(),
            audit=SimpleNamespace(),
            job=SimpleNamespace(id="job-1", tenant_id="tenant-1", created_by="admin-1", activate_on_success=True),
            model=SimpleNamespace(id="model-1", model_name="tenant-model"),
            validated_result={"executor_metadata": {"publish_ready": True}, "serving_model_name": "tenant-model"},
            evaluation_gate={"ready": True},
            runtime_task_id="task-1",
            training_job_id="job-1",
        )

    assert order == ["publish", "verify"]
