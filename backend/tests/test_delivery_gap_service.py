from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.services.delivery_gap_service import DeliveryGapService


@pytest.mark.asyncio
async def test_build_report_tracks_training_runtime_readiness(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "app_public_base_url", "https://docmind.example.com")
    monkeypatch.setattr(
        "app.services.delivery_gap_service.describe_training_runtime",
        lambda: {
            "configured_provider": "script",
            "resolved_provider": "script",
            "ready": True,
            "command_source": "builtin",
            "missing_dependencies": [],
        },
    )
    monkeypatch.setattr(
        "app.services.delivery_gap_service.SecurityPolicyService.evaluate",
        lambda self: {
            "profile": "enterprise",
            "compliant": True,
            "blocking": False,
            "status": "compliant",
            "missing_control_ids": [],
        },
    )

    payload = await DeliveryGapService().build_report("default")

    assert "training_executor_runtime_ready" in payload["completed"]
    assert payload["training_runtime_status"]["ready"] is True
    assert "训练执行器已就绪" in payload["notes"][2]
    assert payload["mobile_auth_status"]["discovery"]["issuer"] == "https://docmind.example.com"
    assert "security_fail_closed_linkage" in payload["completed"]


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
    async def fake_assess(self, tenant_id: str, *, max_age_hours: int | None = None):
        return {"ready": True, "reason": "evaluation_gate_passed"}

    async def fake_eval_summary(self, tenant_id: str, *, limit: int = 10):
        return {"tenant_id": tenant_id, "count": 1, "pass_rate": 1.0, "real_mode_rate": 1.0, "failure_reasons": {}}

    async def fake_deployment_summary(self, tenant_id: str, *, limit: int = 20):
        return {"deployment_gate_counts": {"passed": 1, "blocked": 0, "unknown": 0}, "recent_failures": []}

    monkeypatch.setattr("app.services.delivery_gap_service.EvaluationService.assess_deployment_readiness", fake_assess)
    monkeypatch.setattr("app.services.delivery_gap_service.EvaluationService.summarize_history", fake_eval_summary)
    monkeypatch.setattr("app.services.delivery_gap_service.LLMTrainingService.summarize_deployment", fake_deployment_summary)

    payload = await DeliveryGapService().build_report("default")

    assert "ragas_faithfulness_pipeline_with_real_llm" in payload["completed"]
    assert "full_llmops_regression_gating" in payload["completed"]
    assert "training_deployment_gate_ready" in payload["completed"]
    assert payload["ragas_status"]["real_mode"] is True
    assert "training_artifact_publish_pipeline" in payload["pending"]
    assert "training_publishable_base_model_alignment" in payload["completed"]
    assert payload["training_deployment_gate_status"]["ready_for_activation"] is True


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
    monkeypatch.setenv("DOCMIND_TRAINING_EXPORT_MERGED_MODEL", "false")

    payload = await DeliveryGapService().build_report("default")

    assert "training_artifact_publish_pipeline" in payload["pending"]
    assert "training_publishable_base_model_alignment" in payload["pending"]
    assert payload["training_publish_status"]["publishable_base_aligned"] is False


@pytest.mark.asyncio
async def test_build_report_rejects_tinyllama_family_alignment(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "true")
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
    monkeypatch.setenv("DOCMIND_TRAINING_EXPORT_MERGED_MODEL", "false")

    payload = await DeliveryGapService().build_report("default")

    assert "training_publishable_base_model_alignment" in payload["pending"]
    assert payload["training_publish_status"]["publishable_base_aligned"] is False


@pytest.mark.asyncio
async def test_build_report_accepts_dev_tiny_model_when_merged_export_enabled(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "true")
    monkeypatch.setenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "sshleifer/tiny-gpt2")
    monkeypatch.setenv("DOCMIND_TRAINING_EXPORT_MERGED_MODEL", "true")

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


@pytest.mark.asyncio
async def test_build_report_detects_publish_evidence_from_artifacts_without_db(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    artifact_dir = reports_dir / "model_training" / "default" / "job-1"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "training_request.json").write_text(
        json.dumps({"target_model_name": "default-swu:latest"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "training_result.json").write_text(
        json.dumps({"executor_metadata": {"mode": "executed"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(settings, "llm_training_publish_enabled", True)
    monkeypatch.setattr(settings, "llm_training_publish_command", "ollama create {target_model_name} -f {modelfile_path}")
    monkeypatch.setattr("app.services.delivery_gap_service.shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)

    async def fake_published_models(self):
        return {"default-swu:latest"}

    monkeypatch.setattr(DeliveryGapService, "_load_published_model_names", fake_published_models)
    payload = await DeliveryGapService().build_report("default")

    assert "training_artifact_publish_pipeline" in payload["completed"]
    assert payload["training_publish_status"]["executed_training_present"] is True
    assert payload["training_publish_status"]["published_model_present"] is True
    assert payload["training_publish_status"]["latest_training_job_id"] == "job-1"
    assert payload["training_publish_status"]["latest_model_id"] == "default-swu:latest"


@pytest.mark.asyncio
async def test_build_report_marks_mobile_and_push_gaps(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))

    def fake_mobile_status(self, issuer=None):
        return {
            "enabled": True,
            "ready": True,
            "issues": [],
            "clients": ["docmind-miniapp"],
            "redirect_uris": ["https://servicewechat.com/docmind/callback"],
            "miniapp": {
                "ready": False,
                "issues": ["missing_miniapp_redirect_uri"],
                "clients": ["docmind-miniapp"],
                "redirect_uris": [],
            },
        }

    async def fake_push_health(self, *, tenant_id: str):
        assert tenant_id == "default"
        return {
            "enabled": True,
            "provider": "multi",
            "ready": True,
            "issues": [],
            "providers": {
                "fcm": {"ready": True},
                "apns": {"ready": False},
                "wechat": {"ready": False},
            },
        }

    monkeypatch.setattr("app.services.delivery_gap_service.MobileOAuthService.status", fake_mobile_status)
    monkeypatch.setattr("app.services.delivery_gap_service.PushNotificationService.get_health_summary", fake_push_health)
    monkeypatch.setattr(
        "app.services.delivery_gap_service.SecurityPolicyService.evaluate",
        lambda self: {
            "profile": "enterprise",
            "compliant": True,
            "blocking": False,
            "status": "compliant",
            "missing_control_ids": [],
        },
    )
    async def fake_assess(self, tenant_id: str, *, max_age_hours: int | None = None):
        return {"ready": False, "reason": "evaluation_gate_failed"}

    async def fake_eval_summary(self, tenant_id: str, *, limit: int = 10):
        return {"tenant_id": tenant_id, "count": 2, "pass_rate": 0.5, "real_mode_rate": 0.5, "failure_reasons": {"faithfulness": 1}}

    async def fake_deployment_summary(self, tenant_id: str, *, limit: int = 20):
        return {
            "deployment_gate_counts": {"passed": 0, "blocked": 2, "unknown": 0},
            "recent_failures": [{"deployment_gate_ready": False, "deployment_gate_reason": "evaluation_gate_failed"}],
        }

    monkeypatch.setattr("app.services.delivery_gap_service.EvaluationService.assess_deployment_readiness", fake_assess)
    monkeypatch.setattr("app.services.delivery_gap_service.EvaluationService.summarize_history", fake_eval_summary)
    monkeypatch.setattr("app.services.delivery_gap_service.LLMTrainingService.summarize_deployment", fake_deployment_summary)

    payload = await DeliveryGapService().build_report("default")

    assert "mobile_oauth_runtime_ready" in payload["completed"]
    assert "miniapp_oauth_bootstrap_ready" in payload["pending"]
    assert "training_deployment_gate_ready" in payload["pending"]
    assert "push_notification_runtime_ready" in payload["completed"]
    assert "apns_push_provider_ready" in payload["pending"]
    assert "wechat_push_provider_ready" in payload["pending"]
    assert "security_fail_closed_linkage" in payload["completed"]
    assert payload["training_deployment_gate_status"]["ready_for_activation"] is False
    assert "训练部署门禁尚未满足" in payload["notes"][4]
    assert "推送主链路已就绪" in payload["notes"][6]


@pytest.mark.asyncio
async def test_build_report_marks_security_fail_closed_gap_when_policy_blocking(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "docmind_reports_dir", str(reports_dir))
    monkeypatch.setattr(
        "app.services.delivery_gap_service.SecurityPolicyService.evaluate",
        lambda self: {
            "profile": "financial",
            "compliant": False,
            "blocking": True,
            "status": "blocked",
            "missing_control_ids": ["guardrails_fail_closed", "clamav_fail_closed"],
        },
    )

    payload = await DeliveryGapService().build_report("default")

    assert "security_fail_closed_linkage" in payload["pending"]
    assert "guardrails_fail_closed" in payload["notes"][-1]


