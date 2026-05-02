from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.llm_training_service import LLMTrainingService


class FakeDB:
    def __init__(self):
        self.flushed = 0

    async def flush(self):
        self.flushed += 1


@pytest.mark.asyncio
async def test_verify_model_serving_persists_verify_result(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    model = SimpleNamespace(
        id="model-1",
        tenant_id="tenant-1",
        serving_base_url="http://model.local/v1",
        metrics_json="{}",
        status="published",
        updated_at=None,
    )

    async def fake_get_model(tenant_id: str, model_id: str):
        assert tenant_id == "tenant-1"
        assert model_id == "model-1"
        return model

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            if url.endswith("/health"):
                return FakeResponse(200)
            return FakeResponse(404)

    monkeypatch.setattr(service, "get_model", fake_get_model)
    monkeypatch.setattr("app.services.llm_training_service.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await service.verify_model_serving(tenant_id="tenant-1", model_id="model-1")

    assert result["ok"] is True
    metrics = json.loads(model.metrics_json)
    assert metrics["verify_result"]["ok"] is True
    assert metrics["verify_result"]["reason"] == "verified"
    assert model.status == "verified"


@pytest.mark.asyncio
async def test_summarize_deployment_aggregates_publish_and_verify_states(monkeypatch):
    service = LLMTrainingService(FakeDB(), redis_client=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    jobs = [
        SimpleNamespace(
            id="job-1",
            dataset_name="dataset-1",
            status="completed",
            stage="completed",
            target_model_name="tenant-model-1",
            runtime_task_id="task-1",
            activated_model_id="model-1",
            result_json=json.dumps({"deployment_verification": {"ok": True, "reason": "verified"}}, ensure_ascii=False),
            updated_at=now,
        )
    ]
    models = [
        SimpleNamespace(
            id="model-1",
            tenant_id="tenant-1",
            model_name="tenant-model-1",
            status="verified",
            is_active=True,
            canary_percent=20,
            provider="ollama",
            metrics_json=json.dumps(
                {
                    "publish_result": {"published": True, "publish_ready": True, "reason": "published"},
                },
                ensure_ascii=False,
            ),
            updated_at=now,
        ),
        SimpleNamespace(
            id="model-2",
            tenant_id="tenant-1",
            model_name="tenant-model-2",
            status="registered",
            is_active=False,
            canary_percent=0,
            provider="openai-compatible",
            metrics_json=json.dumps(
                {
                    "publish_result": {"published": False, "publish_ready": False, "reason": "publish_command_failed"},
                    "verify_result": {"ok": False, "reason": "all_health_checks_failed"},
                },
                ensure_ascii=False,
            ),
            updated_at=now,
        ),
    ]

    async def fake_list_jobs(tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        return jobs

    async def fake_list_models(tenant_id: str, limit: int = 20):
        assert tenant_id == "tenant-1"
        return models

    async def fake_active_model(tenant_id: str):
        return {"model_id": "model-1", "model": "tenant-model-1"}

    async def fake_previous_active_model(tenant_id: str):
        return {"model_id": "model-prev", "model": "tenant-model-prev"}

    monkeypatch.setattr(service, "list_jobs", fake_list_jobs)
    monkeypatch.setattr(service, "list_models", fake_list_models)
    monkeypatch.setattr(service, "get_active_model", fake_active_model)
    monkeypatch.setattr(service, "get_previous_active_model", fake_previous_active_model)

    summary = await service.summarize_deployment("tenant-1", limit=10)

    assert summary["publish_counts"]["published"] == 1
    assert summary["publish_counts"]["failed"] == 1
    assert summary["verify_counts"]["verified"] == 1
    assert summary["verify_counts"]["failed"] == 1
    assert summary["failure_category_counts"]["publish_command_failed"] == 1
    assert summary["can_rollback"] is True
    assert summary["recent_failures"][0]["model_id"] == "model-2"
    assert summary["recent_failures"][0]["failure_category"] == "publish_command_failed"


def test_classify_failure_identifies_recoverable_publish_error():
    service = LLMTrainingService(FakeDB(), redis_client=None)

    classification = service.classify_failure("publish_command_failed")

    assert classification["category"] == "publish_command_failed"
    assert classification["recoverable"] is True
    assert "Ollama" in classification["recommended_action"]


def test_resolve_export_summary_uses_clean_error_messages(tmp_path):
    service = LLMTrainingService(FakeDB(), redis_client=None, reports_dir=tmp_path)

    with pytest.raises(ValueError) as missing_root:
        service._resolve_export_summary(source_tenant_id="tenant-a", dataset_name="dataset-a", export_dir=None)
    assert "未找到租户训练导出目录" in str(missing_root.value)

    export_dir = tmp_path / "broken-export"
    export_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError) as missing_manifest:
        service._resolve_export_summary(source_tenant_id="tenant-a", dataset_name="dataset-a", export_dir=str(export_dir))
    assert "训练导出目录不存在 manifest" in str(missing_manifest.value)


@pytest.mark.asyncio
async def test_update_job_stage_persists_failure_result_when_only_error_provided():
    service = LLMTrainingService(FakeDB(), redis_client=None)
    job = SimpleNamespace(
        id="job-1",
        status="running",
        stage="executing",
        updated_at=None,
        completed_at=None,
        error_message=None,
        result_json=None,
    )

    async def fake_get(_model, job_id: str):
        assert job_id == "job-1"
        return job

    service.db.get = fake_get  # type: ignore[attr-defined]

    await service.update_job_stage("job-1", status="failed", stage="failed", error="publish_command_failed")

    payload = json.loads(job.result_json)
    assert payload["ok"] is False
    assert payload["error"] == "publish_command_failed"
    assert payload["failure_classification"]["category"] == "publish_command_failed"
