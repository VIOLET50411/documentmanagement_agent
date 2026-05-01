from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.services.delivery_gap_service import DeliveryGapService


@pytest.mark.asyncio
async def test_build_report_marks_real_ragas_completed(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "evaluation_default.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "faithfulness": 1.0,
                    "answer_relevancy": 0.9,
                    "_meta": {"real_mode": True, "mode": "ragas_ollama"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "false")

    payload = await DeliveryGapService().build_report("default")

    assert "ragas_faithfulness_pipeline_with_real_llm" in payload["completed"]
    assert "full_llmops_regression_gating" in payload["completed"]
    assert payload["ragas_status"]["real_mode"] is True
    assert "training_artifact_publish_pipeline" in payload["pending"]
    assert "training_publishable_base_model_alignment" in payload["completed"]


@pytest.mark.asyncio
async def test_build_report_flags_unpublishable_dev_tiny_model(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "true")
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "sshleifer/tiny-gpt2")

    payload = await DeliveryGapService().build_report("default")

    assert "training_artifact_publish_pipeline" in payload["pending"]
    assert "training_publishable_base_model_alignment" in payload["pending"]
    assert payload["training_publish_status"]["publishable_base_aligned"] is False


@pytest.mark.asyncio
async def test_build_report_accepts_tinyllama_family_alignment(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "true")
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")

    payload = await DeliveryGapService().build_report("default")

    assert "training_publishable_base_model_alignment" in payload["completed"]
    assert payload["training_publish_status"]["publishable_base_aligned"] is True


@pytest.mark.asyncio
async def test_build_report_detects_missing_ollama_cli(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: None)

    payload = await DeliveryGapService().build_report("default")

    assert "training_artifact_publish_pipeline" in payload["pending"]
    assert payload["training_publish_status"]["ollama_cli_available"] is False


@pytest.mark.asyncio
async def test_build_report_marks_publish_pipeline_completed_when_real_evidence_exists(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)

    service = DeliveryGapService()

    async def fake_evidence(_tenant_id: str):
        return {
            "executed_training_present": True,
            "published_model_present": True,
            "latest_training_job_id": "job-1",
            "latest_model_id": "model-1",
        }

    monkeypatch.setattr(service, "_load_training_publish_evidence", fake_evidence)
    payload = await service.build_report("default")

    assert "training_artifact_publish_pipeline" in payload["completed"]
    assert payload["training_publish_status"]["published_model_present"] is True
