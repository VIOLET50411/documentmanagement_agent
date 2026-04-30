from __future__ import annotations

from billiard.exceptions import SoftTimeLimitExceeded

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
    assert "训练任务执行超时" in captured["error"]
