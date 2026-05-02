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


def test_build_gate_fails_when_dataset_summary_lacks_coverage(monkeypatch):
    service = EvaluationService(None, None, reports_dir=Path("."))
    monkeypatch.setattr(settings, "ci_gate_min_eval_unique_docs", 2)
    monkeypatch.setattr(settings, "ci_gate_min_eval_difficulty_buckets", 2)

    gate = service._build_gate(
        {
            "faithfulness": settings.ci_gate_min_faithfulness,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        },
        dataset_summary={"dataset_size": 3, "unique_doc_count": 1, "difficulty_counts": {"basic": 3}},
    )

    assert gate["passed"] is False
    failure_metrics = {item["metric"] for item in gate["failures"]}
    assert "unique_doc_count" in failure_metrics
    assert "difficulty_buckets" in failure_metrics


def test_build_gate_uses_ragas_ollama_thresholds(monkeypatch):
    service = EvaluationService(None, None, reports_dir=Path("."))
    monkeypatch.setattr(settings, "ci_gate_min_answer_relevancy_ragas_ollama", 0.4)

    gate = service._build_gate(
        {
            "faithfulness": 0.9,
            "answer_relevancy": 0.5,
            "context_precision": 0.9,
            "context_recall": 0.9,
            "_meta": {"real_mode": True, "mode": "ragas_ollama"},
        }
    )

    assert gate["passed"] is True
    assert gate["thresholds"]["answer_relevancy"] == 0.4


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


def test_group_documents_prefers_non_synthetic_titles():
    service = EvaluationService(None, None, reports_dir=Path("."))
    rows = [
        ("doc-smoke", "smoke_1.csv", "冒烟内容"),
        ("doc-real", "西南大学预算管理办法", "真实内容"),
    ]

    grouped = service._group_documents(rows, sample_limit=2, exclude_synthetic=True)

    assert len(grouped) == 1
    assert grouped[0]["title"] == "西南大学预算管理办法"


def test_group_documents_falls_back_when_only_synthetic_titles_exist():
    service = EvaluationService(None, None, reports_dir=Path("."))
    rows = [
        ("doc-smoke", "smoke_1.csv", "冒烟内容"),
    ]

    grouped = service._group_documents(rows, sample_limit=2, exclude_synthetic=False)

    assert len(grouped) == 1
    assert grouped[0]["title"] == "smoke_1.csv"


def test_build_seed_documents_returns_enterprise_corpus():
    service = EvaluationService(None, None, reports_dir=Path("."))

    seeds = service._build_seed_documents(sample_limit=3)

    assert len(seeds) == 3
    assert seeds[0]["title"] == "预算管理办法"
    assert "审批" in seeds[1]["chunks"][0]["content"]


@pytest.mark.asyncio
async def test_run_includes_dataset_summary_in_payload(tmp_path: Path):
    service = EvaluationService(None, None, reports_dir=tmp_path)
    service._load_documents = _async_return(  # type: ignore[method-assign]
        [{"id": "doc-1", "title": "预算管理办法", "chunks": [{"content": "预算编制应当遵循统筹安排。预算执行应当严格审批。"}]}]
    )
    service.dataset_generator.generate = _async_return(  # type: ignore[method-assign]
        [
            {
                "question": "预算管理办法第1段的核心内容是什么？",
                "answer": "预算编制应当遵循统筹安排。预算执行应当严格审批。",
                "contexts": ["预算编制应当遵循统筹安排。预算执行应当严格审批。"],
                "context_doc_ids": ["doc-1"],
                "difficulty": "basic",
            }
        ]
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

    result = await service.run("tenant-summary", sample_limit=1)

    assert result["generated_from"]["dataset_summary"]["dataset_size"] == 1
    assert result["generated_from"]["dataset_summary"]["unique_doc_count"] == 1
    assert result["generated_from"]["dataset_summary"]["difficulty_counts"]["basic"] == 1


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
