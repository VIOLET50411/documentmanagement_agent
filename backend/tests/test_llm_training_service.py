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
