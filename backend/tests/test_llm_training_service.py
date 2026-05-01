from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.llm_training_service import LLMTrainingService


class FakeDB:
    def __init__(self):
        self.flushed = 0

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_update_model_canary_percent_clamps_range(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        canary_percent=0,
        updated_at=None,
        metrics_json="{}",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        assert tenant_id == "tenant-1"
        assert model_id == "model-1"
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)

    updated = await service.update_model_canary_percent(
        tenant_id="tenant-1",
        model_id="model-1",
        canary_percent=130,
        actor_id="admin-1",
    )

    assert updated.canary_percent == 100
    assert "canary_updated_by" in updated.metrics_json


@pytest.mark.asyncio
async def test_verify_model_serving_reports_success(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        serving_base_url="http://model.local/v1",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_deploy_health_path", "/healthz")
    monkeypatch.setattr(settings, "llm_training_deploy_verify_timeout_seconds", 5)

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            if url.endswith("/healthz"):
                return FakeResponse(200)
            return FakeResponse(404)

    monkeypatch.setattr("app.services.llm_training_service.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await service.verify_model_serving(tenant_id="tenant-1", model_id="model-1")

    assert result["ok"] is True
    assert result["url"].endswith("/healthz")


@pytest.mark.asyncio
async def test_verify_model_serving_reports_failure(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        serving_base_url="http://model.local/v1",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_deploy_health_path", "")
    monkeypatch.setattr(settings, "llm_training_deploy_verify_timeout_seconds", 5)

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            return FakeResponse(503)

    monkeypatch.setattr("app.services.llm_training_service.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await service.verify_model_serving(tenant_id="tenant-1", model_id="model-1")

    assert result["ok"] is False
    assert len(result["attempts"]) >= 2


@pytest.mark.asyncio
async def test_publish_model_artifact_reports_unsupported_base_model(tmp_path: Path, monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    artifact_dir = tmp_path / "artifact"
    adapter_dir = artifact_dir / "adapter"
    adapter_dir.mkdir(parents=True)
    (artifact_dir / "adapter_manifest.json").write_text(
        '{"hf_base_model":"Qwen/Qwen2.5-7B-Instruct","adapter_dir":"' + str(adapter_dir).replace("\\", "/") + '"}',
        encoding="utf-8",
    )
    (artifact_dir / "Modelfile").write_text("FROM qwen2.5:7b\n", encoding="utf-8")
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        artifact_dir=str(artifact_dir),
        model_name="tenant-model",
        base_model="qwen2.5:7b",
        serving_base_url="http://ollama:11434/v1",
        serving_model_name="qwen2.5:7b",
        provider="openai-compatible",
        status="registered",
        updated_at=None,
        metrics_json="{}",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    result = await service.publish_model_artifact(tenant_id="tenant-1", model_id="model-1")
    assert result["publish_ready"] is False
    assert result["reason"] == "unsupported_ollama_adapter_base_model"


@pytest.mark.asyncio
async def test_publish_model_artifact_runs_publish_command(tmp_path: Path, monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    artifact_dir = tmp_path / "artifact"
    adapter_dir = artifact_dir / "adapter"
    adapter_dir.mkdir(parents=True)
    (artifact_dir / "adapter_manifest.json").write_text(
        '{"hf_base_model":"meta-llama/Llama-3.1-8B-Instruct","adapter_dir":"' + str(adapter_dir).replace("\\", "/") + '"}',
        encoding="utf-8",
    )
    (artifact_dir / "Modelfile").write_text("FROM llama3.1:8b\nADAPTER ./adapter\n", encoding="utf-8")
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        artifact_dir=str(artifact_dir),
        model_name="tenant-model",
        base_model="llama3.1:8b",
        serving_base_url="http://ollama:11434/v1",
        serving_model_name="llama3.1:8b",
        provider="openai-compatible",
        status="registered",
        updated_at=None,
        metrics_json="{}",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"published", b"")

    captured = {}

    async def fake_create_subprocess_shell(command, cwd=None, env=None, stdout=None, stderr=None):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProcess()

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr(settings, "llm_training_publish_workdir", str(tmp_path))
    monkeypatch.setattr("app.services.llm_training_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr("app.services.llm_training_service.asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    result = await service.publish_model_artifact(tenant_id="tenant-1", model_id="model-1")
    assert result["publish_ready"] is True
    assert result["serving_model_name"] == "tenant-model"
    assert model.serving_model_name == "tenant-model"
    assert model.status == "published"
    assert "ollama create tenant-model" in captured["command"]
    assert captured["cwd"] == str(artifact_dir.resolve())


@pytest.mark.asyncio
async def test_publish_model_artifact_reports_missing_ollama_shared_mount(tmp_path: Path, monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    artifact_dir = tmp_path / "artifact"
    adapter_dir = artifact_dir / "adapter"
    adapter_dir.mkdir(parents=True)
    (artifact_dir / "adapter_manifest.json").write_text(
        '{"hf_base_model":"meta-llama/Llama-3.1-8B-Instruct","adapter_dir":"' + str(adapter_dir).replace("\\", "/") + '"}',
        encoding="utf-8",
    )
    (artifact_dir / "Modelfile").write_text("FROM llama3.1:8b\nADAPTER ./adapter\n", encoding="utf-8")
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        artifact_dir=str(artifact_dir),
        model_name="tenant-model",
        base_model="llama3.1:8b",
        serving_base_url="http://ollama:11434/v1",
        serving_model_name="llama3.1:8b",
        provider="openai-compatible",
        status="registered",
        updated_at=None,
        metrics_json="{}",
        notes=None,
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return (b"", b"Error: no Modelfile or safetensors files found")

    async def fake_create_subprocess_shell(command, cwd=None, env=None, stdout=None, stderr=None):
        return FakeProcess()

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.llm_training_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr("app.services.llm_training_service.asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    result = await service.publish_model_artifact(tenant_id="tenant-1", model_id="model-1")

    assert result["publish_ready"] is False
    assert result["reason"] == "publish_command_failed"
    assert "Ollama" in result["message"]
    assert "reports" in result["message"]


@pytest.mark.asyncio
async def test_reconcile_job_runtime_state_marks_terminal_from_runtime():
    db = FakeDB()
    service = LLMTrainingService(db, redis_client=None)
    job = SimpleNamespace(
        status="running",
        stage="executing",
        error_message=None,
        result_json=None,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        completed_at=None,
    )

    changed = await service.reconcile_job_runtime_state(
        job,
        {
            "item": {"status": "failed", "stage": "failed", "error": "redis unavailable", "updated_at": "2026-04-30T12:00:00"},
            "result": {"ok": False, "error": "redis unavailable"},
        },
    )

    assert changed is True
    assert job.status == "failed"
    assert job.stage == "failed"
    assert job.error_message == "redis unavailable"
    assert '"ok": false' in job.result_json.lower()
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_reconcile_job_runtime_state_marks_stale_runtime(monkeypatch):
    db = FakeDB()
    service = LLMTrainingService(db, redis_client=None)
    monkeypatch.setattr(settings, "llm_training_runtime_stale_seconds", 60)
    job = SimpleNamespace(
        status="running",
        stage="executing",
        error_message=None,
        result_json=None,
        updated_at=datetime(2026, 4, 30, 12, 0, 0),
        completed_at=None,
    )

    changed = await service.reconcile_job_runtime_state(
        job,
        {
            "item": {
                "status": "running",
                "stage": "executing",
                "updated_at": "2026-04-30T12:00:00",
                "stage_payload": {"heartbeat_at": "2026-04-30T12:00:00"},
            }
        },
        stale_after_seconds=60,
    )

    assert changed is True
    assert job.status == "failed"
    assert job.stage == "failed"
    assert job.error_message == "training_runtime_stale>60s"
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_reconcile_model_registry_states_aligns_active_flags():
    db = FakeDB()
    active_model = SimpleNamespace(id="model-active", is_active=False, status="registered", provider="ollama", metrics_json="{}")
    stale_model = SimpleNamespace(id="model-stale", is_active=True, status="active", provider="openai-compatible", metrics_json="{}")
    service = LLMTrainingService(db, redis_client=None)

    async def fake_get_active_model(tenant_id: str):
        assert tenant_id == "tenant-1"
        return {"model_id": "model-active"}

    service.get_active_model = fake_get_active_model  # type: ignore[method-assign]
    changed = await service.reconcile_model_registry_states("tenant-1", [active_model, stale_model])

    assert changed is True
    assert active_model.is_active is True
    assert active_model.status == "active"
    assert stale_model.is_active is False
    assert stale_model.status == "registered"
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_reconcile_job_result_consistency_fails_plan_only_completion():
    db = FakeDB()
    service = LLMTrainingService(db, redis_client=None)
    job = SimpleNamespace(
        status="completed",
        stage="completed",
        error_message=None,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        result_json='{"executor_metadata":{"mode":"plan_only"}}',
    )

    changed = await service.reconcile_job_result_consistency(job)

    assert changed is True
    assert job.status == "failed"
    assert job.stage == "failed"
    assert job.error_message == "training_plan_only_result"
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_reconcile_jobs_returns_batch_stats():
    db = FakeDB()
    service = LLMTrainingService(db, redis_client=None)
    running_job = SimpleNamespace(
        runtime_task_id="task-1",
        status="running",
        stage="executing",
        error_message=None,
        result_json=None,
        updated_at=datetime(2026, 4, 30, 12, 0, 0),
        completed_at=None,
    )
    completed_job = SimpleNamespace(
        runtime_task_id="task-2",
        status="completed",
        stage="completed",
        error_message=None,
        result_json='{"executor_metadata":{"mode":"plan_only"}}',
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    stats = await service.reconcile_jobs(
        [running_job, completed_job],
        runtime_payloads={
            "task-1": {
                "item": {
                    "status": "running",
                    "stage": "executing",
                    "updated_at": "2026-04-30T12:00:00",
                    "stage_payload": {"heartbeat_at": "2026-04-30T12:00:00"},
                }
            }
        },
        stale_after_seconds=60,
    )

    assert stats == {
        "scanned": 2,
        "changed": 2,
        "stale_failed": 1,
        "plan_only_failed": 1,
    }


@pytest.mark.asyncio
async def test_reconcile_job_runtime_state_fail_closes_existing_runtime_error():
    db = FakeDB()
    service = LLMTrainingService(db, redis_client=None)
    job = SimpleNamespace(
        status="running",
        stage="executing",
        error_message="training_runtime_stale>300s",
        result_json=None,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        completed_at=None,
    )

    changed = await service.reconcile_job_runtime_state(job, runtime_payload=None, stale_after_seconds=300)

    assert changed is True
    assert job.status == "failed"
    assert job.stage == "failed"
    assert db.flushed == 1
