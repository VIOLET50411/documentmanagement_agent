import json
from pathlib import Path

import pytest

from app.config import settings
from app.dependencies import STARTUP_SCHEMA_COMPATIBILITY_STATEMENTS
from app.services.evaluation_service import EvaluationService


def test_build_gate_passes_when_metrics_meet_thresholds():
    service = EvaluationService(None, None, reports_dir=Path("."))

    gate = service._build_gate(
        {
            "faithfulness": settings.ci_gate_min_faithfulness,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        }
    )

    assert gate["passed"] is True
    assert gate["failures"] == []


def test_build_gate_fails_when_metric_below_threshold():
    service = EvaluationService(None, None, reports_dir=Path("."))

    gate = service._build_gate(
        {
            "faithfulness": settings.ci_gate_min_faithfulness - 0.1,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        }
    )

    assert gate["passed"] is False
    assert gate["failures"][0]["metric"] == "faithfulness"


@pytest.mark.asyncio
async def test_latest_reads_new_payload_shape(tmp_path: Path):
    tenant_id = "tenant-test"
    json_path = tmp_path / f"evaluation_{tenant_id}.json"
    md_path = tmp_path / f"evaluation_{tenant_id}.md"
    dataset_path = tmp_path / f"evaluation_{tenant_id}.dataset.json"

    payload = {
        "metrics": {
            "faithfulness": 0.91,
            "answer_relevancy": 0.88,
            "context_precision": 0.9,
            "context_recall": 0.86,
            "_meta": {"real_mode": False, "mode": "fallback"},
        },
        "gate": {"passed": False, "failures": [{"metric": "real_mode"}]},
        "dataset_size": 3,
        "generated_at": "2026-04-30T10:00:00+00:00",
        "generated_from": {"tenant_id": tenant_id, "sample_limit": 3, "document_count": 2},
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text("# report", encoding="utf-8")
    dataset_path.write_text(json.dumps([{"q": 1}, {"q": 2}, {"q": 3}], ensure_ascii=False), encoding="utf-8")

    result = await EvaluationService(None, None, reports_dir=tmp_path).latest(tenant_id)

    assert result["exists"] is True
    assert result["metrics"]["faithfulness"] == 0.91
    assert result["gate"]["passed"] is False
    assert result["dataset_size"] == 3
    assert result["generated_at"] == "2026-04-30T10:00:00+00:00"


@pytest.mark.asyncio
async def test_latest_supports_legacy_metrics_only_payload(tmp_path: Path):
    tenant_id = "tenant-legacy"
    json_path = tmp_path / f"evaluation_{tenant_id}.json"
    md_path = tmp_path / f"evaluation_{tenant_id}.md"
    dataset_path = tmp_path / f"evaluation_{tenant_id}.dataset.json"

    legacy_metrics = {
        "faithfulness": 1.0,
        "answer_relevancy": 0.0,
        "context_precision": 0.0,
        "context_recall": 0.0,
        "sample_count": 1,
        "_meta": {"real_mode": True, "mode": "ragas_ollama"},
    }
    json_path.write_text(json.dumps(legacy_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text("# legacy report", encoding="utf-8")
    dataset_path.write_text(json.dumps([{"q": 1}], ensure_ascii=False), encoding="utf-8")

    result = await EvaluationService(None, None, reports_dir=tmp_path).latest(tenant_id)

    assert result["exists"] is True
    assert result["metrics"]["faithfulness"] == 1.0
    assert result["gate"]["passed"] is False
    assert result["generated_from"]["legacy_report"] is True
    assert result["generated_at"] is None


@pytest.mark.asyncio
async def test_run_reports_progress_stages(tmp_path: Path):
    service = EvaluationService(None, None, reports_dir=tmp_path)
    service._load_documents = _async_return(  # type: ignore[method-assign]
        [{"id": "doc-1", "title": "文档", "chunks": [{"content": "内容"}]}]
    )
    service.dataset_generator.generate = _async_return(  # type: ignore[method-assign]
        [{"question": "Q", "answer": "A", "contexts": ["C"]}]
    )
    service.runner.evaluate = _async_return(  # type: ignore[method-assign]
        {
            "faithfulness": settings.ci_gate_min_faithfulness,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        }
    )
    service.audit.log_event = _async_return(None)  # type: ignore[method-assign]

    seen: list[str] = []

    async def on_progress(stage: str, _payload: dict):
        seen.append(stage)

    result = await service.run("tenant-progress", sample_limit=1, progress_callback=on_progress)

    assert result["dataset_size"] == 1
    assert result["generated_at"]
    assert seen == ["dataset_building", "evaluating", "reporting", "completed"]


def test_startup_schema_compatibility_includes_invitation_revocation_column():
    assert any("user_invitations" in stmt and "revoked_at" in stmt for stmt in STARTUP_SCHEMA_COMPATIBILITY_STATEMENTS)


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
