from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.config import settings
from app.training.executor import (
    MockTrainingExecutor,
    RemoteTrainingExecutor,
    ScriptTrainingExecutor,
    TrainingExecutionRequest,
    TrainingExecutor,
    build_training_executor,
)


@pytest.mark.asyncio
async def test_mock_training_executor_writes_artifacts(tmp_path: Path):
    request = TrainingExecutionRequest(
        job_id="job-1",
        tenant_id="default",
        dataset_name="swu_public_docs",
        base_model="qwen2.5:7b",
        export_dir=str(tmp_path / "export"),
        manifest_path=str(tmp_path / "export" / "manifest.json"),
        target_model_name="default-swu",
        train_records=24,
        val_records=3,
        artifact_dir=str(tmp_path / "artifacts"),
        provider="mock",
    )

    result = await MockTrainingExecutor().execute(request)

    assert (tmp_path / "artifacts" / "adapter_manifest.json").exists()
    assert (tmp_path / "artifacts" / "model_card.md").exists()
    assert result["artifact_dir"] == str(tmp_path / "artifacts")


def test_training_executor_validate_result_requires_required_fields():
    executor = TrainingExecutor()
    with pytest.raises(ValueError, match="artifact_dir"):
        executor.validate_result({"serving_base_url": "http://localhost", "serving_model_name": "qwen"})


def test_training_executor_validate_result_rejects_plan_only_payload(tmp_path: Path):
    executor = TrainingExecutor()
    artifact_dir = tmp_path / "artifact"
    artifact_dir.mkdir()
    with pytest.raises(ValueError, match="仅输出训练计划"):
        executor.validate_result(
            {
                "artifact_dir": str(artifact_dir),
                "adapter_dir": "",
                "executed": False,
                "serving_base_url": "http://localhost",
                "serving_model_name": "tenant-model",
                "executor_metadata": {"mode": "plan_only"},
            }
        )


def test_build_training_executor_supports_remote_aliases(monkeypatch):
    monkeypatch.setattr(settings, "llm_training_executor_script_command", "")
    assert build_training_executor("mock").__class__.__name__ == "MockTrainingExecutor"
    assert build_training_executor("remote").__class__.__name__ == "RemoteTrainingExecutor"
    assert build_training_executor("api").__class__.__name__ == "RemoteTrainingExecutor"
    assert build_training_executor("script").__class__.__name__ == "ScriptTrainingExecutor"


@pytest.mark.asyncio
async def test_remote_training_executor_supports_async_job_polling(monkeypatch):
    settings.llm_training_executor_api_base_url = "http://trainer.local"
    settings.llm_training_executor_timeout_seconds = 30
    settings.llm_training_executor_poll_interval_seconds = 1

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.poll_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json=None, headers=None):
            return FakeResponse({"job_id": "job-123", "status": "queued"})

        async def get(self, url, headers=None):
            self.poll_count += 1
            if self.poll_count == 1:
                return FakeResponse({"job_id": "job-123", "status": "running"})
            return FakeResponse(
                {
                    "job_id": "job-123",
                    "status": "completed",
                    "result": {
                        "artifact_dir": "/tmp/model",
                        "serving_base_url": "http://ollama:11434/v1",
                        "serving_model_name": "qwen2.5:1.5b",
                    },
                }
            )

    monkeypatch.setattr("app.training.executor.httpx.AsyncClient", FakeClient)

    request = TrainingExecutionRequest(
        job_id="job-1",
        tenant_id="default",
        dataset_name="swu_public_docs",
        base_model="qwen2.5:7b",
        export_dir="/tmp/export",
        manifest_path="/tmp/export/manifest.json",
        target_model_name="default-swu",
        train_records=24,
        val_records=3,
        artifact_dir="/tmp/artifacts",
        provider="remote",
    )

    result = await RemoteTrainingExecutor().execute(request)
    assert result["artifact_dir"] == "/tmp/model"
    assert result["serving_model_name"] == "qwen2.5:1.5b"
    assert result["executor_metadata"]["executor"] == "remote"
    assert result["executor_metadata"]["job_id"] == "job-123"


@pytest.mark.asyncio
async def test_script_training_executor_reads_result_file(tmp_path: Path, monkeypatch):
    python_executable = sys.executable.replace("\\", "/")
    settings.llm_training_executor_script_command = (
        f"\"{python_executable}\" -c \"import json,os,pathlib; "
        "artifact=pathlib.Path(os.environ['DOCMIND_TRAINING_ARTIFACT_DIR']); "
        "(artifact / 'training_result.json').write_text(json.dumps({{"
        "'artifact_dir': str(artifact), "
        "'adapter_dir': str(artifact), "
        "'executed': True, "
        "'serving_base_url': 'http://localhost:11434/v1', "
        "'serving_model_name': 'tenant-model'}}), encoding='utf-8')\""
    )
    settings.llm_training_executor_script_workdir = str(tmp_path)

    request = TrainingExecutionRequest(
        job_id="job-script-1",
        tenant_id="default",
        dataset_name="swu_public_docs",
        base_model="qwen2.5:7b",
        export_dir=str(tmp_path / "export"),
        manifest_path=str(tmp_path / "export" / "manifest.json"),
        target_model_name="default-swu",
        train_records=24,
        val_records=3,
        artifact_dir=str(tmp_path / "artifacts"),
        provider="script",
    )

    result = await ScriptTrainingExecutor().execute(request)

    request_json = json.loads((tmp_path / "artifacts" / "training_request.json").read_text(encoding="utf-8"))
    assert request_json["job_id"] == "job-script-1"
    assert result["executed"] is True
    assert result["serving_model_name"] == "tenant-model"
    assert result["executor_metadata"]["executor"] == "script"
