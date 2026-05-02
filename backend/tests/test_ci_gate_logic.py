import json

import pytest

from app.config import settings
from scripts.ci_gate import _enforce_evaluation_gate, _enforce_security_controls, _resolve_metric_thresholds


def test_ci_gate_rejects_failed_evaluation_gate():
    with pytest.raises(RuntimeError, match="evaluation quality gate failed"):
        _enforce_evaluation_gate(
            {"gate": {"passed": False, "failures": [{"metric": "faithfulness"}]}},
            {"faithfulness": 0.7},
            {"real_mode": True, "mode": "ragas_api"},
        )


def test_ci_gate_rejects_heuristic_mode_when_real_required(monkeypatch):
    monkeypatch.setattr(settings, "ci_gate_require_real_ragas", True)
    with pytest.raises(RuntimeError, match="heuristic mode returned"):
        _enforce_evaluation_gate(
            {"gate": {"passed": True, "failures": []}},
            {"faithfulness": 0.9, "_meta": {"real_mode": True, "mode": "fallback"}},
            {"real_mode": True, "mode": "fallback"},
        )


def test_ci_gate_accepts_real_ragas_gate(monkeypatch):
    monkeypatch.setattr(settings, "ci_gate_require_real_ragas", True)
    _enforce_evaluation_gate(
        {
            "gate": {
                "passed": True,
                "failures": [],
                "dataset_summary": {"unique_doc_count": 2, "difficulty_counts": {"basic": 1, "grounded": 1}},
            }
        },
        {"faithfulness": 0.95, "_meta": {"real_mode": True, "mode": "ragas_api"}},
        {"real_mode": True, "mode": "ragas_api"},
    )


def test_ci_gate_rejects_low_dataset_coverage(monkeypatch):
    monkeypatch.setattr(settings, "ci_gate_min_eval_unique_docs", 2)
    monkeypatch.setattr(settings, "ci_gate_min_eval_difficulty_buckets", 2)
    with pytest.raises(RuntimeError, match="unique_doc_count too low"):
        _enforce_evaluation_gate(
            {
                "gate": {
                    "passed": True,
                    "failures": [],
                    "dataset_summary": {"unique_doc_count": 1, "difficulty_counts": {"basic": 3}},
                }
            },
            {"faithfulness": 0.95, "_meta": {"real_mode": True, "mode": "ragas_api"}},
            {"real_mode": True, "mode": "ragas_api"},
        )


def test_ci_gate_rejects_financial_security_without_presidio():
    payload = {
        "profile": "financial",
        "compliant": True,
        "guardrails_sidecar": {"configured": True, "alive": True, "fail_closed": True},
        "pii": {"masking_enabled": True, "presidio_enabled": False},
        "clamav_health": {"enabled": True, "status": "online"},
    }
    with pytest.raises(RuntimeError, match="presidio-backed pii"):
        _enforce_security_controls(payload)


def test_ci_gate_accepts_financial_security_controls():
    payload = {
        "profile": "financial",
        "compliant": True,
        "guardrails_sidecar": {"configured": True, "alive": True, "fail_closed": True},
        "pii": {"masking_enabled": True, "presidio_enabled": True},
        "clamav_health": {"enabled": True, "status": "online"},
    }
    _enforce_security_controls(payload)


def test_ci_gate_uses_mode_specific_thresholds_for_ragas_ollama():
    thresholds = _resolve_metric_thresholds({"mode": "ragas_ollama"})

    assert thresholds["answer_relevancy"] == settings.ci_gate_min_answer_relevancy_ragas_ollama
