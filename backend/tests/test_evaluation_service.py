import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.dependencies import STARTUP_SCHEMA_COMPATIBILITY_STATEMENTS
from app.evaluation.golden_dataset import GoldenDatasetGenerator
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
    monkeypatch.setattr(settings, "ci_gate_min_eval_dataset_size", 3)
    monkeypatch.setattr(settings, "ci_gate_min_eval_unique_docs", 2)
    monkeypatch.setattr(settings, "ci_gate_min_eval_difficulty_buckets", 2)
    monkeypatch.setattr(settings, "ci_gate_min_eval_grounded_samples", 1)
    monkeypatch.setattr(settings, "ci_gate_min_eval_avg_context_length", 80)
    monkeypatch.setattr(settings, "ci_gate_min_eval_task_type_buckets", 3)
    monkeypatch.setattr(settings, "ci_gate_min_eval_compare_samples", 1)
    monkeypatch.setattr(settings, "ci_gate_min_eval_follow_up_samples", 1)

    gate = service._build_gate(
        {
            "faithfulness": settings.ci_gate_min_faithfulness,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        },
        dataset_summary={
            "dataset_size": 3,
            "unique_doc_count": 1,
            "difficulty_counts": {"basic": 3},
            "task_type_counts": {"summary": 3},
            "grounded_sample_count": 0,
            "compare_sample_count": 0,
            "follow_up_sample_count": 0,
            "avg_context_length": 32,
        },
    )

    assert gate["passed"] is False
    failure_metrics = {item["metric"] for item in gate["failures"]}
    assert "unique_doc_count" in failure_metrics
    assert "difficulty_buckets" in failure_metrics
    assert "grounded_sample_count" in failure_metrics
    assert "avg_context_length" in failure_metrics
    assert "task_type_buckets" in failure_metrics
    assert "compare_sample_count" in failure_metrics
    assert "follow_up_sample_count" in failure_metrics


def test_build_gate_fails_when_dataset_size_below_threshold(monkeypatch):
    service = EvaluationService(None, None, reports_dir=Path("."))
    monkeypatch.setattr(settings, "ci_gate_min_eval_dataset_size", 5)

    gate = service._build_gate(
        {
            "faithfulness": settings.ci_gate_min_faithfulness,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        },
        dataset_summary={
            "dataset_size": 4,
            "unique_doc_count": 4,
            "difficulty_counts": {"basic": 2, "grounded": 2},
            "task_type_counts": {"summary": 1, "grounded_requirement": 1, "compare": 1, "follow_up": 1},
            "grounded_sample_count": 2,
            "compare_sample_count": 1,
            "follow_up_sample_count": 1,
            "avg_context_length": 120,
        },
    )

    assert gate["passed"] is False
    assert any(item["metric"] == "dataset_size" for item in gate["failures"])


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


def test_summarize_dataset_tracks_grounded_samples_and_task_types():
    service = EvaluationService(None, None, reports_dir=Path("."))

    summary = service._summarize_dataset(
        [
            {
                "context_doc_ids": ["doc-1"],
                "difficulty": "grounded",
                "task_type": "grounded_requirement",
                "contexts": ["这是第一段比较完整的上下文内容，用来验证 grounded 样本统计。"],
            },
            {
                "context_doc_ids": ["doc-2"],
                "difficulty": "compare",
                "task_type": "compare",
                "contexts": ["这是第二段上下文内容，也比较完整，用来验证 compare 题型统计。"],
            },
            {
                "context_doc_ids": ["doc-2"],
                "difficulty": "follow_up",
                "task_type": "follow_up",
                "contexts": ["继续追问时依旧要基于原文证据回答，这里用来验证 follow_up 题型统计。"],
            },
        ]
    )

    assert summary["dataset_size"] == 3
    assert summary["unique_doc_count"] == 2
    assert summary["grounded_sample_count"] == 1
    assert summary["compare_sample_count"] == 1
    assert summary["follow_up_sample_count"] == 1
    assert summary["task_type_counts"]["grounded_requirement"] == 1
    assert summary["task_type_counts"]["compare"] == 1
    assert summary["task_type_counts"]["follow_up"] == 1
    assert summary["avg_context_length"] >= 10


def test_group_documents_prioritizes_business_chunks_and_multiple_docs():
    service = EvaluationService(None, None, reports_dir=Path("."))

    rows = [
        (
            "doc-budget",
            "西南大学2024年度部门预算.html",
            "2 目 录 一、学校基本情况 ................................ 3",
            "swu 2024 department budget",
            2,
        ),
        (
            "doc-budget",
            "西南大学2024年度部门预算.html",
            "三、部门预算情况说明 我校2024年收支总预算582,276.35万元，其中本年收入预算445,059.97万元。",
            "三、部门预算情况说明",
            22,
        ),
        (
            "doc-budget",
            "西南大学2024年度部门预算.html",
            "二、部门预算报表 西南大学收支预算总表 单位：万元 收入 支出 项目 预算数 项目 预算数。",
            "二、部门预算报表",
            14,
        ),
        (
            "doc-travel",
            "西南大学国内差旅费管理办法.html",
            "第三条 差旅费报销应当提供审批单、行程单和合法票据，经部门负责人审核后报销。",
            "第三条 差旅费报销要求",
            5,
        ),
        (
            "doc-travel",
            "西南大学国内差旅费管理办法.html",
            "学校概况 西南大学位于重庆市北碚区。",
            "学校概况",
            1,
        ),
    ]

    grouped = service._group_documents(rows, sample_limit=4, exclude_synthetic=True)

    assert len(grouped) == 2
    budget_doc = next(item for item in grouped if item["id"] == "doc-budget")
    travel_doc = next(item for item in grouped if item["id"] == "doc-travel")
    assert "预算情况说明" in budget_doc["chunks"][0]["content"] or "预算总表" in budget_doc["chunks"][0]["content"]
    assert "差旅费报销" in travel_doc["chunks"][0]["content"]
    assert all("目录" not in chunk["content"] for chunk in budget_doc["chunks"][:1])


def test_score_eval_chunk_penalizes_toc_and_rewards_budget_evidence():
    service = EvaluationService(None, None, reports_dir=Path("."))

    toc_score = service._score_eval_chunk(
        title="西南大学2024年度部门预算.html",
        section_title="swu 2024 department budget",
        content="2 目 录 一、学校基本情况 ................................ 3",
        chunk_index=2,
    )
    budget_score = service._score_eval_chunk(
        title="西南大学2024年度部门预算.html",
        section_title="三、部门预算情况说明",
        content="我校2024年收支总预算582,276.35万元，其中本年收入预算445,059.97万元。",
        chunk_index=22,
    )

    assert budget_score > toc_score


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
async def test_assess_deployment_readiness_blocks_missing_report(tmp_path: Path):
    service = EvaluationService(None, None, reports_dir=tmp_path)

    result = await service.assess_deployment_readiness("tenant-missing", max_age_hours=24)

    assert result["ready"] is False
    assert result["reason"] == "evaluation_missing"


@pytest.mark.asyncio
async def test_assess_deployment_readiness_blocks_stale_report(tmp_path: Path):
    tenant_id = "tenant-stale"
    payload = {
        "metrics": {
            "faithfulness": 0.95,
            "answer_relevancy": 0.9,
            "context_precision": 0.9,
            "context_recall": 0.9,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        },
        "gate": {"passed": True, "failures": []},
        "dataset_size": 5,
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
        "generated_from": {"tenant_id": tenant_id, "dataset_summary": {"dataset_size": 5}},
    }
    (tmp_path / f"evaluation_{tenant_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / f"evaluation_{tenant_id}.md").write_text("# report", encoding="utf-8")
    (tmp_path / f"evaluation_{tenant_id}.dataset.json").write_text(json.dumps([1, 2, 3, 4, 5]), encoding="utf-8")

    result = await EvaluationService(None, None, reports_dir=tmp_path).assess_deployment_readiness(tenant_id, max_age_hours=24)

    assert result["ready"] is False
    assert result["reason"] == "evaluation_stale"


@pytest.mark.asyncio
async def test_assess_deployment_readiness_accepts_fresh_passed_report(tmp_path: Path):
    tenant_id = "tenant-fresh"
    payload = {
        "metrics": {
            "faithfulness": 0.95,
            "answer_relevancy": 0.9,
            "context_precision": 0.9,
            "context_recall": 0.9,
            "_meta": {"real_mode": True, "mode": "ragas_api"},
        },
        "gate": {"passed": True, "failures": []},
        "dataset_size": 5,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_from": {"tenant_id": tenant_id, "dataset_summary": {"dataset_size": 5}},
    }
    (tmp_path / f"evaluation_{tenant_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (tmp_path / f"evaluation_{tenant_id}.md").write_text("# report", encoding="utf-8")
    (tmp_path / f"evaluation_{tenant_id}.dataset.json").write_text(json.dumps([1, 2, 3, 4, 5]), encoding="utf-8")

    result = await EvaluationService(None, None, reports_dir=tmp_path).assess_deployment_readiness(tenant_id, max_age_hours=24)

    assert result["ready"] is True
    assert result["reason"] == "evaluation_gate_passed"


@pytest.mark.asyncio
async def test_evaluation_history_and_summary_use_redis_snapshots(tmp_path: Path):
    class FakeRedis:
        def __init__(self):
            self.lists: dict[str, list[str]] = {}

        async def lpush(self, key: str, value: str):
            self.lists.setdefault(key, []).insert(0, value)
            return len(self.lists[key])

        async def ltrim(self, key: str, start: int, end: int):
            stop = None if end == -1 else end + 1
            self.lists[key] = self.lists.get(key, [])[start:stop]
            return True

        async def expire(self, _key: str, _ttl: int):
            return True

        async def lrange(self, key: str, start: int, end: int):
            stop = None if end == -1 else end + 1
            return self.lists.get(key, [])[start:stop]

        async def llen(self, key: str):
            return len(self.lists.get(key, []))

    redis_client = FakeRedis()
    service = EvaluationService(None, redis_client, reports_dir=tmp_path)
    await service._persist_history_snapshot(
        "tenant-1",
        {
            "metrics": {
                "faithfulness": 0.95,
                "answer_relevancy": 0.9,
                "context_precision": 0.91,
                "context_recall": 0.92,
                "_meta": {"real_mode": True, "mode": "ragas_api"},
            },
            "gate": {"passed": True, "failures": []},
            "dataset_size": 5,
            "generated_at": "2026-05-03T10:00:00+00:00",
            "generated_from": {"tenant_id": "tenant-1"},
        },
    )
    await service._persist_history_snapshot(
        "tenant-1",
        {
            "metrics": {
                "faithfulness": 0.6,
                "answer_relevancy": 0.75,
                "context_precision": 0.7,
                "context_recall": 0.65,
                "_meta": {"real_mode": False, "mode": "fallback"},
            },
            "gate": {"passed": False, "failures": [{"metric": "faithfulness"}, {"metric": "real_mode"}]},
            "dataset_size": 3,
            "generated_at": "2026-05-03T11:00:00+00:00",
            "generated_from": {"tenant_id": "tenant-1"},
        },
    )

    history = await service.history("tenant-1", limit=10)
    summary = await service.summarize_history("tenant-1", limit=10)

    assert history["total"] == 2
    assert len(history["items"]) == 2
    assert history["items"][0]["generated_at"] == "2026-05-03T11:00:00+00:00"
    assert summary["count"] == 2
    assert summary["pass_rate"] == 0.5
    assert summary["real_mode_rate"] == 0.5
    assert summary["failure_reasons"]["faithfulness"] == 1
    assert summary["failure_reasons"]["real_mode"] == 1
    assert summary["drift"]["available"] is True
    assert summary["drift"]["gate_changed"] is True
    assert summary["drift"]["real_mode_changed"] is True
    assert summary["drift"]["dataset_size_delta"] == -2
    assert summary["drift"]["metrics"]["faithfulness"] == -0.35


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


def test_golden_dataset_grounded_pair_uses_sentence_anchored_answer():
    generator = GoldenDatasetGenerator()

    pairs = generator._build_sentence_pairs(
        "差旅审批制度",
        "员工出差前应当在系统中提交差旅申请。申请内容包括出差事由、地点、时间和预计费用。",
        {"id": "doc-1"},
        0,
    )

    grounded = next(item for item in pairs if item["difficulty"] == "grounded")
    assert grounded["question"] == "根据差旅审批制度，这一段明确了什么要求？"
    assert grounded["answer"] == "员工出差前应当在系统中提交差旅申请。"
    basic = next(item for item in pairs if item["difficulty"] == "basic")
    assert basic["question"] == "根据差旅审批制度，第1段开头的原文要求是什么？"


def test_golden_dataset_builds_compare_follow_up_and_version_pairs():
    generator = GoldenDatasetGenerator()

    pairs = generator._build_sentence_pairs(
        "采购管理办法（2024版）",
        "采购申请应当先提交部门审批。审批通过后方可进入比价流程。该制度自2024年3月1日起执行。",
        {"id": "doc-2"},
        0,
    )

    task_types = {item["task_type"] for item in pairs}
    assert "follow_up" in task_types
    assert "compare" in task_types
    assert "version" in task_types
    compare_pair = next(item for item in pairs if item["task_type"] == "compare")
    assert "| 对比项 | 内容 |" in compare_pair["answer"]


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
                "task_type": "summary",
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
    assert result["generated_from"]["dataset_summary"]["task_type_counts"]["summary"] == 1


def _async_return(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
