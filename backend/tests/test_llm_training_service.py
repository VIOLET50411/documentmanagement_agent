import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.llm_training_service import LLMTrainingService


def test_llm_training_service_resolves_latest_export_summary(tmp_path: Path):
    reports = tmp_path / "reports"
    old_dir = reports / "domain_tuning" / "public_cold_start" / "swu_public_docs_20260429_100000"
    new_dir = reports / "domain_tuning" / "public_cold_start" / "swu_public_docs_20260429_120000"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "manifest.json").write_text('{"training_readiness":{"train_records":30}}', encoding="utf-8")
    (new_dir / "manifest.json").write_text('{"training_readiness":{"train_records":88,"ready_for_sft":true}}', encoding="utf-8")

    service = LLMTrainingService(db=SimpleNamespace(), redis_client=None, reports_dir=reports)
    summary = service._resolve_export_summary(source_tenant_id="public_cold_start", dataset_name="swu_public_docs", export_dir=None)

    assert summary["training_readiness"]["train_records"] == 88
    assert summary["export_dir"].endswith("swu_public_docs_20260429_120000")


@pytest.mark.asyncio
async def test_llm_training_service_create_job_rejects_small_training_set(tmp_path: Path):
    reports = tmp_path / "reports"
    export_dir = reports / "domain_tuning" / "public_cold_start" / "swu_public_docs_20260429_100000"
    export_dir.mkdir(parents=True)
    (export_dir / "manifest.json").write_text(json.dumps({"training_readiness": {"train_records": 5, "val_records": 1}}), encoding="utf-8")

    class FakeDB:
        def add(self, _item):
            return None

        async def flush(self):
            return None

    service = LLMTrainingService(db=FakeDB(), redis_client=None, reports_dir=reports)
    with pytest.raises(ValueError, match="训练样本不足"):
        await service.create_job(
            tenant_id="default",
            source_tenant_id="public_cold_start",
            dataset_name="swu_public_docs",
            export_dir=str(export_dir),
            base_model="qwen2.5:7b",
            provider="mock",
            activate_on_success=True,
            actor_id="admin",
        )


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str):
        self.store[key] = value


class FakeModel:
    def __init__(self, model_id: str, tenant_id: str, active: bool = False):
        self.id = model_id
        self.tenant_id = tenant_id
        self.provider = "openai-compatible"
        self.serving_base_url = "http://localhost:11434/v1"
        self.serving_model_name = model_id
        self.api_key = ""
        self.base_model = "qwen2.5:7b"
        self.artifact_dir = f"/artifacts/{model_id}"
        self.status = "registered"
        self.is_active = active
        self.metrics_json = "{}"
        self.activated_at = None
        self.updated_at = None


class FakeResult:
    def __init__(self, item):
        self.item = item

    def scalar_one_or_none(self):
        return self.item


class FakeDBForActivate:
    def __init__(self, tenant_id: str):
        self.models = {
            "model-a": FakeModel("model-a", tenant_id, active=True),
            "model-b": FakeModel("model-b", tenant_id, active=False),
        }

    async def execute(self, _query):
        return FakeResult(next((item for item in self.models.values() if item.is_active), None))

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_llm_training_service_activate_and_rollback_previous_model():
    tenant_id = "default"
    redis_client = FakeRedis()
    db = FakeDBForActivate(tenant_id)
    service = LLMTrainingService(db=db, redis_client=redis_client, reports_dir="reports")

    async def fake_get_model(runtime_tenant_id: str, model_id: str):
        assert runtime_tenant_id == tenant_id
        return db.models.get(model_id)

    service.get_model = fake_get_model  # type: ignore[method-assign]

    model_b = await service.activate_model(tenant_id=tenant_id, model_id="model-b", actor_id="admin")
    assert model_b.is_active is True
    previous_payload = json.loads(redis_client.store[service._previous_active_model_key(tenant_id)])
    assert previous_payload["model_id"] == "model-a"

    rolled_back = await service.rollback_active_model(tenant_id=tenant_id, actor_id="admin")
    assert rolled_back["ok"] is True
    assert rolled_back["rolled_back_to"]["model_id"] == "model-a"
