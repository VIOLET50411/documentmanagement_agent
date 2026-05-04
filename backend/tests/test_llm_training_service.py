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


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value


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
async def test_activate_model_requires_manual_approval_when_enabled(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        is_active=False,
        status="published",
        activated_at=None,
        updated_at=None,
        metrics_json="{}",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        assert tenant_id == "tenant-1"
        assert model_id == "model-1"
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", True)

    with pytest.raises(ValueError):
        await service.activate_model(tenant_id="tenant-1", model_id="model-1", actor_id="admin-1")


@pytest.mark.asyncio
async def test_activate_model_blocks_unpublished_model(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        is_active=False,
        status="registered",
        activated_at=None,
        updated_at=None,
        metrics_json="{}",
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        assert tenant_id == "tenant-1"
        assert model_id == "model-1"
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", False)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", False)
    monkeypatch.setattr(settings, "llm_training_deploy_verify_enabled", False)

    with pytest.raises(ValueError, match="publish incomplete"):
        await service.activate_model(tenant_id="tenant-1", model_id="model-1", actor_id="admin-1")


@pytest.mark.asyncio
async def test_activate_model_blocks_stale_evaluation_gate(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        is_active=False,
        status="published",
        activated_at=None,
        updated_at=None,
        metrics_json='{"publish_result":{"published":true},"verify_result":{"ok":true,"reason":"verified"}}',
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    async def fake_assess(self, tenant_id: str, *, max_age_hours: int | None = None):
        assert tenant_id == "tenant-1"
        assert max_age_hours == settings.llm_training_eval_max_age_hours
        return {"ready": False, "reason": "evaluation_stale", "message": "evaluation report is stale"}

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", False)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", True)
    monkeypatch.setattr(settings, "llm_training_deploy_verify_enabled", True)
    monkeypatch.setattr("app.services.llm_training_service.EvaluationService.assess_deployment_readiness", fake_assess)

    with pytest.raises(ValueError, match="evaluation report is stale"):
        await service.activate_model(tenant_id="tenant-1", model_id="model-1", actor_id="admin-1")

    assert '"reason": "evaluation_stale"' in model.metrics_json


@pytest.mark.asyncio
async def test_activate_model_allows_auto_deploy_bypass_for_preverification(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        is_active=False,
        status="published",
        activated_at=None,
        updated_at=None,
        metrics_json='{"publish_result":{"published":true}}',
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    async def fake_execute(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "get_model", fake_get_model)
    async def fake_active_model(_tenant_id: str):
        return None
    monkeypatch.setattr(service, "get_active_model", fake_active_model)
    monkeypatch.setattr(service.db, "execute", fake_execute, raising=False)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", False)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", False)
    monkeypatch.setattr(settings, "llm_training_deploy_verify_enabled", True)

    activated = await service.activate_model(
        tenant_id="tenant-1",
        model_id="model-1",
        actor_id="admin-1",
        require_preverified=False,
    )

    assert activated.status == "active"
    assert activated.is_active is True


@pytest.mark.asyncio
async def test_record_model_approval_updates_metrics(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        metrics_json="{}",
        notes="",
        updated_at=None,
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", True)

    approval = await service.record_model_approval(
        tenant_id="tenant-1",
        model_id="model-1",
        approved=True,
        actor_id="admin-1",
        reason="qa passed",
    )

    assert approval["decision"] == "approved"
    assert approval["ready"] is True
    assert "approved" in model.metrics_json


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
    monkeypatch.setattr("app.services.llm_training_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
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
async def test_publish_model_artifact_prefers_merged_full_model_import(tmp_path: Path, monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    artifact_dir = tmp_path / "artifact"
    adapter_dir = artifact_dir / "adapter"
    merged_model_dir = artifact_dir / "merged_model"
    adapter_dir.mkdir(parents=True)
    merged_model_dir.mkdir(parents=True)
    (merged_model_dir / "model.safetensors").write_text("dummy", encoding="utf-8")
    (artifact_dir / "adapter_manifest.json").write_text(
        (
            '{"hf_base_model":"TinyLlama/TinyLlama-1.1B-Chat-v1.0",'
            '"adapter_dir":"' + str(adapter_dir).replace("\\", "/") + '",'
            '"merged_model_dir":"' + str(merged_model_dir).replace("\\", "/") + '"}'
        ),
        encoding="utf-8",
    )
    (artifact_dir / "Modelfile").write_text(f"FROM {str(merged_model_dir).replace(chr(92), '/')}\n", encoding="utf-8")
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        artifact_dir=str(artifact_dir),
        model_name="tenant-model",
        base_model="tinyllama",
        serving_base_url="http://ollama:11434/v1",
        serving_model_name="tinyllama",
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
    monkeypatch.setattr("app.services.llm_training_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr("app.services.llm_training_service.asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    result = await service.publish_model_artifact(tenant_id="tenant-1", model_id="model-1")

    assert result["published"] is True
    assert result["publish_mode"] == "full_model_import"
    assert captured["env"]["DOCMIND_TRAINING_PUBLISH_MODE"] == "full_model_import"
    assert captured["env"]["DOCMIND_TRAINING_MERGED_MODEL_DIR"] == str(merged_model_dir.resolve())


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
async def test_rollback_active_model_restores_previous_model(monkeypatch):
    redis_client = FakeRedis()
    redis_client.data["llm:previous_active_model:tenant-1"] = '{"model_id":"model-prev","tenant_id":"tenant-1"}'
    service = LLMTrainingService(FakeDB(), redis_client=redis_client)
    model = SimpleNamespace(
        id="model-prev",
        tenant_id="tenant-1",
        provider="ollama",
        serving_base_url="http://ollama:11434/v1",
        serving_model_name="tenant-model-prev",
        artifact_dir="/tmp/model-prev",
        activated_at=None,
        api_key="",
    )

    async def fake_activate_model(*, tenant_id: str, model_id: str, actor_id: str | None = None):
        assert tenant_id == "tenant-1"
        assert model_id == "model-prev"
        assert actor_id == "admin-1"
        return model

    monkeypatch.setattr(service, "activate_model", fake_activate_model)

    result = await service.rollback_active_model(tenant_id="tenant-1", actor_id="admin-1")

    assert result["ok"] is True
    assert result["rolled_back_to"]["model_id"] == "model-prev"
    assert result["rolled_back_to"]["model"] == "tenant-model-prev"


@pytest.mark.asyncio
async def test_rollback_active_model_requires_previous_active_model():
    service = LLMTrainingService(FakeDB(), redis_client=None)

    with pytest.raises(ValueError):
        await service.rollback_active_model(tenant_id="tenant-1", actor_id="admin-1")


@pytest.mark.asyncio
async def test_activate_model_persists_previous_active_snapshot(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        is_active=False,
        status="published",
        activated_at=None,
        updated_at=None,
        metrics_json='{"publish_result":{"published":true},"verify_result":{"ok":true,"reason":"verified"}}',
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        return model

    async def fake_active_model(_tenant_id: str):
        return {"model_id": "model-prev", "tenant_id": "tenant-1", "model": "tenant-model-prev"}

    async def fake_execute(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(service, "get_active_model", fake_active_model)
    monkeypatch.setattr(service.db, "execute", fake_execute, raising=False)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", False)
    monkeypatch.setattr(settings, "llm_training_require_evaluation_gate", False)
    monkeypatch.setattr(settings, "llm_training_deploy_verify_enabled", True)

    await service.activate_model(
        tenant_id="tenant-1",
        model_id="model-1",
        actor_id="admin-1",
    )

    assert '"previous_active_model"' in model.metrics_json
    assert '"model-prev"' in model.metrics_json


@pytest.mark.asyncio
async def test_get_previous_active_model_falls_back_to_active_model_metrics():
    class FakeResult:
        def __init__(self, item):
            self.item = item

        def scalar_one_or_none(self):
            return self.item

    class FakeDBWithExecute(FakeDB):
        def __init__(self, item):
            super().__init__()
            self.item = item

        async def execute(self, *args, **kwargs):
            return FakeResult(self.item)

    active_model = SimpleNamespace(
        metrics_json='{"previous_active_model":{"model_id":"model-prev","tenant_id":"tenant-1","model":"tenant-model-prev"}}'
    )
    service = LLMTrainingService(FakeDBWithExecute(active_model), redis_client=None)

    payload = await service.get_previous_active_model("tenant-1")

    assert payload == {"model_id": "model-prev", "tenant_id": "tenant-1", "model": "tenant-model-prev"}


@pytest.mark.asyncio
async def test_publish_model_artifact_reports_missing_artifact_dir(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        artifact_dir="Z:/not-found/artifact",
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

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)

    result = await service.publish_model_artifact(tenant_id="tenant-1", model_id="model-1")

    assert result["publish_ready"] is False
    assert result["reason"] == "artifact_dir_missing"
    assert "artifact" in result["message"]


@pytest.mark.asyncio
async def test_publish_model_artifact_sanitizes_ansi_sequences(tmp_path: Path, monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    artifact_dir = tmp_path / "artifact"
    adapter_dir = artifact_dir / "adapter"
    adapter_dir.mkdir(parents=True)
    (artifact_dir / "adapter_manifest.json").write_text(
        '{"hf_base_model":"meta-llama/Llama-3.1-8B-Instruct","adapter_dir":"'
        + str(adapter_dir).replace("\\", "/")
        + '"}',
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
            return (b"", b"\x1b[?2026hError: no Modelfile or safetensors files found\x1b[?25l")

    async def fake_create_subprocess_shell(command, cwd=None, env=None, stdout=None, stderr=None):
        return FakeProcess()

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.llm_training_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr("app.services.llm_training_service.asyncio.create_subprocess_shell", fake_create_subprocess_shell)

    result = await service.publish_model_artifact(tenant_id="tenant-1", model_id="model-1")

    assert "\x1b" not in result["message"]
    assert "\x1b" not in (model.notes or "")


@pytest.mark.asyncio
async def test_retry_failed_publications_retries_only_recoverable_models(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    recoverable = SimpleNamespace(
        id="model-retry",
        model_name="tenant-model-retry",
        status="registered",
        metrics_json='{"publish_result":{"published":false,"reason":"publish_command_failed","message":"failed"}}',
    )
    skipped = SimpleNamespace(
        id="model-skip",
        model_name="tenant-model-skip",
        status="registered",
        metrics_json='{"publish_result":{"published":false,"reason":"unsupported_ollama_adapter_base_model","message":"unsupported"}}',
    )

    async def fake_list_models(tenant_id: str, limit: int = 50):
        assert tenant_id == "tenant-1"
        return [recoverable, skipped]

    async def fake_publish_model_artifact(*, tenant_id: str, model_id: str):
        assert tenant_id == "tenant-1"
        assert model_id == "model-retry"
        return {"published": True, "publish_ready": True, "reason": "published", "message": "ok"}

    async def fake_verify_model_serving(*, tenant_id: str, model_id: str):
        return {"ok": True, "reason": "verified"}

    monkeypatch.setattr(service, "list_models", fake_list_models)
    monkeypatch.setattr(service, "publish_model_artifact", fake_publish_model_artifact)
    monkeypatch.setattr(service, "verify_model_serving", fake_verify_model_serving)

    result = await service.retry_failed_publications(tenant_id="tenant-1", limit=5, verify=True)

    assert result["attempted_count"] == 1
    assert result["skipped_count"] == 1
    assert result["attempted"][0]["model_id"] == "model-retry"
    assert result["attempted"][0]["verify_result"]["ok"] is True
    assert result["skipped"][0]["model_id"] == "model-skip"


@pytest.mark.asyncio
async def test_summarize_rollout_aggregates_jobs_models_and_rollback(monkeypatch):
    redis_client = FakeRedis()
    redis_client.data["llm:active_model:tenant-1"] = '{"model_id":"model-active","tenant_id":"tenant-1","model":"tenant-model-active"}'
    redis_client.data["llm:previous_active_model:tenant-1"] = '{"model_id":"model-prev","tenant_id":"tenant-1","model":"tenant-model-prev"}'
    service = LLMTrainingService(FakeDB(), redis_client=redis_client)

    jobs = [
        SimpleNamespace(
            id="job-1",
            dataset_name="dataset-a",
            status="running",
            stage="deploying",
            target_model_name="tenant-model-a",
            runtime_task_id="task-1",
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
        SimpleNamespace(
            id="job-2",
            dataset_name="dataset-b",
            status="failed",
            stage="failed",
            target_model_name="tenant-model-b",
            runtime_task_id="task-2",
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
    ]
    models = [
        SimpleNamespace(
            id="model-1",
            model_name="tenant-model-active",
            status="active",
            is_active=True,
            canary_percent=20,
            provider="ollama",
            metrics_json='{"publish_result":{"published":true}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
        SimpleNamespace(
            id="model-2",
            model_name="tenant-model-staged",
            status="registered",
            is_active=False,
            canary_percent=0,
            provider="openai-compatible",
            metrics_json='{"publish_result":{"publish_ready":true}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
    ]

    async def fake_list_jobs(tenant_id: str, limit: int = 100):
        assert tenant_id == "tenant-1"
        return jobs

    async def fake_list_models(tenant_id: str, limit: int = 100):
        assert tenant_id == "tenant-1"
        return models

    monkeypatch.setattr(service, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(service, "list_models", fake_list_models)
    monkeypatch.setattr(
        "app.services.llm_training_service.describe_training_runtime",
        lambda: {
            "configured_provider": "script",
            "resolved_provider": "script",
            "ready": True,
            "command_source": "builtin",
        },
    )

    summary = await service.summarize_rollout("tenant-1", limit=10)

    assert summary["jobs"]["total"] == 2
    assert summary["jobs"]["running"] == 1
    assert summary["jobs"]["failed"] == 1
    assert summary["models"]["active"] == 1
    assert summary["models"]["canary"] == 1
    assert summary["models"]["publish_state_counts"]["published"] == 1
    assert summary["models"]["publish_state_counts"]["publish_ready"] == 1
    assert summary["can_rollback"] is True
    assert summary["executor_runtime"]["ready"] is True
    assert summary["executor_runtime"]["command_source"] == "builtin"
    assert summary["active_model"]["model_id"] == "model-active"
    assert summary["previous_active_model"]["model_id"] == "model-prev"


@pytest.mark.asyncio
async def test_summarize_deployment_aggregates_failure_recoverability(monkeypatch):
    redis_client = FakeRedis()
    redis_client.data["llm:active_model:tenant-1"] = '{"model_id":"model-active","tenant_id":"tenant-1","model":"tenant-model-active"}'
    service = LLMTrainingService(FakeDB(), redis_client=redis_client)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", True)

    jobs = [
        SimpleNamespace(
            id="job-1",
            dataset_name="dataset-a",
            status="completed",
            stage="completed",
            target_model_name="tenant-model-a",
            runtime_task_id="task-1",
            activated_model_id="model-ok",
            result_json='{"deployment_verification":{"ok":true,"reason":"verified"}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    ]
    models = [
        SimpleNamespace(
            id="model-ok",
            model_name="tenant-model-active",
            status="active",
            is_active=True,
            canary_percent=0,
            provider="ollama",
            metrics_json='{"publish_result":{"published":true},"verify_result":{"ok":true,"reason":"verified"},"approval":{"decision":"approved","approved":true}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
        SimpleNamespace(
            id="model-recoverable",
            model_name="tenant-model-recoverable",
            status="registered",
            is_active=False,
            canary_percent=0,
            provider="openai-compatible",
            metrics_json='{"publish_result":{"published":false,"reason":"publish_command_failed","message":"failed"},"deployment_gate":{"ready":true,"reason":"evaluation_gate_passed"},"approval":{"decision":"approved","approved":true}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
        SimpleNamespace(
            id="model-nonrecoverable",
            model_name="tenant-model-nonrecoverable",
            status="registered",
            is_active=False,
            canary_percent=0,
            provider="openai-compatible",
            metrics_json='{"publish_result":{"published":false,"reason":"unsupported_ollama_adapter_base_model","message":"unsupported"},"deployment_gate":{"ready":false,"reason":"evaluation_gate_failed"},"approval":{"decision":"rejected","approved":false,"reason":"qa_rejected"}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
    ]

    async def fake_list_jobs(tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        return jobs

    async def fake_list_models(tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        return models

    monkeypatch.setattr(service, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(service, "list_models", fake_list_models)

    summary = await service.summarize_deployment("tenant-1", limit=20)

    assert summary["publish_counts"]["published"] == 1
    assert summary["publish_counts"]["failed"] == 2
    assert summary["verify_counts"]["verified"] == 1
    assert summary["deployment_gate_counts"]["passed"] == 1
    assert summary["deployment_gate_counts"]["blocked"] == 1
    assert summary["deployment_gate_counts"]["unknown"] == 1
    assert summary["approval_counts"]["approved"] == 2
    assert summary["approval_counts"]["rejected"] == 1
    assert summary["recoverable_failure_count"] == 1
    assert summary["non_recoverable_failure_count"] == 1
    assert summary["failure_category_counts"]["publish_command_failed"] == 1
    assert summary["failure_category_counts"]["approval_rejected"] == 1
    assert summary["top_recommendations"][0]["count"] == 1
    assert summary["recent_failures"][0]["model_id"] in {"model-recoverable", "model-nonrecoverable"}
    assert "deployment_gate_ready" in summary["recent_failures"][0]
    assert "approval_decision" in summary["recent_failures"][0]


@pytest.mark.asyncio
async def test_summarize_deployment_prioritizes_approval_pending_failure(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    monkeypatch.setattr(settings, "llm_training_require_manual_approval", True)

    models = [
        SimpleNamespace(
            id="model-pending",
            model_name="tenant-model-pending",
            status="active",
            is_active=True,
            canary_percent=0,
            provider="ollama",
            metrics_json='{"publish_result":{"published":true},"verify_result":{"ok":true,"reason":"verified"}}',
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
    ]

    async def fake_list_jobs(tenant_id: str, limit: int = 20):
        return []

    async def fake_list_models(tenant_id: str, limit: int = 20):
        return models

    async def fake_get_active_model(tenant_id: str):
        return {"model_id": "model-pending", "model": "tenant-model-pending"}

    async def fake_get_previous_active_model(tenant_id: str):
        return None

    monkeypatch.setattr(service, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(service, "list_models", fake_list_models)
    monkeypatch.setattr(service, "get_active_model", fake_get_active_model)
    monkeypatch.setattr(service, "get_previous_active_model", fake_get_previous_active_model)

    summary = await service.summarize_deployment("tenant-1", limit=20)

    assert summary["approval_counts"]["pending"] == 1
    assert summary["recent_failures"][0]["failure_category"] == "approval_pending"
    assert summary["recent_failures"][0]["approval_reason"] == "approval_pending"


@pytest.mark.asyncio
async def test_summarize_deployment_excludes_retired_failures(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    retired_model = SimpleNamespace(
        id="model-retired",
        model_name="tenant-model-retired",
        status="retired",
        is_active=False,
        canary_percent=0,
        provider="openai-compatible",
        metrics_json='{"publish_result":{"published":false,"reason":"unsupported_ollama_adapter_base_model"},"retired":{"retired_at":"2026-05-03T10:00:00"}}',
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    async def fake_list_jobs(tenant_id: str, limit: int = 20):
        return []

    async def fake_list_models(tenant_id: str, limit: int = 20):
        return [retired_model]

    monkeypatch.setattr(service, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(service, "list_models", fake_list_models)
    async def fake_get_active_model(tenant_id: str):
        return None

    async def fake_get_previous_active_model(tenant_id: str):
        return None

    monkeypatch.setattr(service, "get_active_model", fake_get_active_model)
    monkeypatch.setattr(service, "get_previous_active_model", fake_get_previous_active_model)

    summary = await service.summarize_deployment("tenant-1", limit=20)

    assert summary["publish_counts"]["failed"] == 0
    assert summary["non_recoverable_failure_count"] == 0
    assert summary["retired_count"] == 1
    assert summary["recent_failures"] == []


@pytest.mark.asyncio
async def test_retire_nonrecoverable_models_marks_only_nonrecoverable(monkeypatch):
    db = FakeDB()
    service = LLMTrainingService(db, redis_client=None)
    retired_candidate = SimpleNamespace(
        id="model-retire",
        model_name="tenant-model-retire",
        status="registered",
        is_active=False,
        provider="openai-compatible",
        metrics_json='{"publish_result":{"published":false,"reason":"unsupported_ollama_adapter_base_model","message":"unsupported"}}',
        notes=None,
        updated_at=None,
    )
    recoverable_candidate = SimpleNamespace(
        id="model-retry",
        model_name="tenant-model-retry",
        status="registered",
        is_active=False,
        provider="openai-compatible",
        metrics_json='{"publish_result":{"published":false,"reason":"publish_command_failed","message":"failed"}}',
        notes=None,
        updated_at=None,
    )
    active_model = SimpleNamespace(
        id="model-active",
        model_name="tenant-model-active",
        status="active",
        is_active=True,
        provider="ollama",
        metrics_json='{"publish_result":{"published":true}}',
        notes=None,
        updated_at=None,
    )

    async def fake_list_models(tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        return [retired_candidate, recoverable_candidate, active_model]

    monkeypatch.setattr(service, "list_models", fake_list_models)

    payload = await service.retire_nonrecoverable_models(
        tenant_id="tenant-1",
        limit=10,
        dry_run=False,
        actor_id="admin-1",
    )

    assert payload["retired_count"] == 1
    assert payload["changed_count"] == 1
    assert retired_candidate.status == "retired"
    assert "unsupported_ollama_adapter_base_model" in retired_candidate.notes
    assert "unsupported_base_model" in retired_candidate.notes
    assert recoverable_candidate.status == "registered"
    assert active_model.status == "active"
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_classify_failure_maps_adapter_dir_missing():
    service = LLMTrainingService(FakeDB(), redis_client=None)

    failure = service.classify_failure("adapter_dir_missing")

    assert failure["category"] == "artifact_missing"
    assert failure["recoverable"] is False


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
