"""Evaluation orchestration service with report, gates, and audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.evaluation.golden_dataset import GoldenDatasetGenerator
from app.evaluation.ragas_runner import RagasRunner
from app.evaluation.report_generator import ReportGenerator
from app.models.db.document import Document, DocumentChunk
from app.models.db.user import User
from app.services.security_audit_service import SecurityAuditService


class EvaluationService:
    """Run tenant-scoped evaluation and produce delivery-grade outputs."""

    def __init__(self, db: AsyncSession | None, redis_client=None, reports_dir: Path | None = None):
        self.db = db
        self.redis = redis_client
        self.reports_dir = Path(reports_dir) if reports_dir is not None else Path(settings.docmind_reports_dir)
        self.dataset_generator = GoldenDatasetGenerator()
        self.runner = RagasRunner()
        self.report_generator = ReportGenerator()
        self.audit = SecurityAuditService(redis_client, db)

    async def run(
        self,
        tenant_id: str,
        *,
        sample_limit: int = 100,
        actor: User | None = None,
        progress_callback: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        await self._notify_progress(
            progress_callback,
            "dataset_building",
            {"tenant_id": tenant_id, "sample_limit": max(sample_limit, 1)},
        )
        documents = await self._load_documents(tenant_id, sample_limit=max(sample_limit, 1))
        dataset = await self.dataset_generator.generate(documents, count=max(sample_limit, 1))
        dataset_summary = self._summarize_dataset(dataset)
        await self._notify_progress(
            progress_callback,
            "evaluating",
            {"tenant_id": tenant_id, "dataset_size": len(dataset), "document_count": len(documents), "dataset_summary": dataset_summary},
        )
        metrics = await self.runner.evaluate(dataset=dataset)
        gate = self._build_gate(metrics, dataset_summary=dataset_summary)

        self.reports_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"evaluation_{tenant_id}"
        json_path = self.reports_dir / f"{base_name}.json"
        markdown_path = self.reports_dir / f"{base_name}.md"
        dataset_path = self.reports_dir / f"{base_name}.dataset.json"

        payload = {
            "metrics": metrics,
            "gate": gate,
            "dataset_size": len(dataset),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_from": {
                "tenant_id": tenant_id,
                "sample_limit": max(sample_limit, 1),
                "document_count": len(documents),
                "dataset_summary": dataset_summary,
            },
        }
        await self._notify_progress(
            progress_callback,
            "reporting",
            {"tenant_id": tenant_id, "dataset_size": len(dataset), "gate_passed": gate["passed"]},
        )
        self.report_generator.generate_json_report(payload, output_path=str(json_path))
        self.report_generator.generate_markdown_report(payload, output_path=str(markdown_path))
        dataset_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        await self._persist_history_snapshot(tenant_id, payload)

        await self.audit.log_event(
            tenant_id,
            "evaluation_run",
            "low" if gate["passed"] else "medium",
            f"evaluation completed: passed={gate['passed']}, dataset_size={len(dataset)}",
            user_id=getattr(actor, "id", None),
            target="evaluation",
            result="ok" if gate["passed"] else "warning",
            metadata={
                "dataset_size": len(dataset),
                "dataset_summary": dataset_summary,
                "gate": gate,
                "metrics": metrics,
            },
        )
        await self._notify_progress(
            progress_callback,
            "completed",
            {"tenant_id": tenant_id, "dataset_size": len(dataset), "gate_passed": gate["passed"]},
        )

        return payload | {
            "report_json": str(json_path),
            "report_markdown": str(markdown_path),
            "dataset_path": str(dataset_path),
        }

    async def latest(self, tenant_id: str) -> dict[str, Any]:
        base_name = f"evaluation_{tenant_id}"
        json_path = self.reports_dir / f"{base_name}.json"
        markdown_path = self.reports_dir / f"{base_name}.md"
        dataset_path = self.reports_dir / f"{base_name}.dataset.json"

        payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else None
        normalized_payload = self._normalize_saved_payload(payload) if payload else None
        dataset_size = len(json.loads(dataset_path.read_text(encoding="utf-8"))) if dataset_path.exists() else 0
        return {
            "exists": normalized_payload is not None,
            "metrics": normalized_payload.get("metrics") if normalized_payload else None,
            "gate": normalized_payload.get("gate") if normalized_payload else None,
            "generated_at": normalized_payload.get("generated_at") if normalized_payload else None,
            "generated_from": normalized_payload.get("generated_from") if normalized_payload else None,
            "markdown": markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else None,
            "dataset_size": dataset_size,
            "report_json": str(json_path),
            "report_markdown": str(markdown_path),
        }

    async def history(self, tenant_id: str, *, limit: int = 30) -> dict[str, Any]:
        if self.redis is None:
            return {"items": [], "total": 0}
        key = self._history_key(tenant_id)
        rows = await self.redis.lrange(key, 0, max(limit - 1, 0))
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                parsed = json.loads(row)
            except json.JSONDecodeError:
                continue
            normalized = self._normalize_saved_payload(parsed)
            items.append(
                {
                    "generated_at": normalized.get("generated_at"),
                    "dataset_size": normalized.get("dataset_size"),
                    "generated_from": normalized.get("generated_from") or {},
                    "gate": normalized.get("gate") or {},
                    "metrics": normalized.get("metrics") or {},
                }
            )
        total = await self.redis.llen(key)
        return {"items": items, "total": int(total or 0)}

    async def summarize_history(self, tenant_id: str, *, limit: int = 30) -> dict[str, Any]:
        history = await self.history(tenant_id, limit=limit)
        items = history.get("items") or []
        if not items:
            return {
                "tenant_id": tenant_id,
                "count": 0,
                "pass_rate": 0.0,
                "real_mode_rate": 0.0,
                "latest_generated_at": None,
                "failure_reasons": {},
                "metric_averages": {},
                "trend": [],
                "drift": {"available": False, "reason": "insufficient_history"},
            }

        passed_count = 0
        real_mode_count = 0
        failure_reasons: dict[str, int] = {}
        metric_buckets: dict[str, list[float]] = {
            "faithfulness": [],
            "answer_relevancy": [],
            "context_precision": [],
            "context_recall": [],
        }
        trend: list[dict[str, Any]] = []

        for item in items:
            gate = item.get("gate") if isinstance(item.get("gate"), dict) else {}
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            meta = metrics.get("_meta") if isinstance(metrics.get("_meta"), dict) else {}
            if gate.get("passed"):
                passed_count += 1
            if meta.get("real_mode"):
                real_mode_count += 1
            for failure in gate.get("failures") or []:
                reason = str((failure or {}).get("metric") or "unknown")
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            for metric_name in metric_buckets:
                try:
                    metric_buckets[metric_name].append(float(metrics.get(metric_name)))
                except (TypeError, ValueError):
                    continue
            trend.append(
                {
                    "generated_at": item.get("generated_at"),
                    "passed": bool(gate.get("passed")),
                    "real_mode": bool(meta.get("real_mode")),
                    "dataset_size": item.get("dataset_size"),
                    "faithfulness": metrics.get("faithfulness"),
                    "answer_relevancy": metrics.get("answer_relevancy"),
                    "context_precision": metrics.get("context_precision"),
                    "context_recall": metrics.get("context_recall"),
                }
            )

        metric_averages = {
            key: round(sum(values) / len(values), 4)
            for key, values in metric_buckets.items()
            if values
        }
        drift = self._build_drift_summary(items)
        return {
            "tenant_id": tenant_id,
            "count": len(items),
            "pass_rate": round(passed_count / len(items), 4),
            "real_mode_rate": round(real_mode_count / len(items), 4),
            "latest_generated_at": items[0].get("generated_at"),
            "failure_reasons": dict(sorted(failure_reasons.items(), key=lambda item: (-item[1], item[0]))),
            "metric_averages": metric_averages,
            "trend": trend,
            "drift": drift,
        }

    async def assess_deployment_readiness(self, tenant_id: str, *, max_age_hours: int | None = None) -> dict[str, Any]:
        latest = await self.latest(tenant_id)
        gate = latest.get("gate") if isinstance(latest.get("gate"), dict) else {}
        metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
        effective_max_age_hours = max(int(max_age_hours or 24), 1)

        if not latest.get("exists"):
            return {
                "ready": False,
                "reason": "evaluation_missing",
                "message": "未找到最新评估报告，已阻止自动发布和激活。",
                "generated_at": None,
                "gate": gate,
                "metrics": metrics,
                "max_age_hours": effective_max_age_hours,
            }

        generated_at = self._parse_iso_datetime(latest.get("generated_at"))
        if generated_at is None:
            return {
                "ready": False,
                "reason": "evaluation_timestamp_missing",
                "message": "评估报告缺少生成时间，已阻止自动发布和激活。",
                "generated_at": latest.get("generated_at"),
                "gate": gate,
                "metrics": metrics,
                "max_age_hours": effective_max_age_hours,
            }

        age_seconds = max((datetime.now(timezone.utc) - generated_at).total_seconds(), 0.0)
        stale = age_seconds > effective_max_age_hours * 3600
        if stale:
            return {
                "ready": False,
                "reason": "evaluation_stale",
                "message": f"评估报告已过期，已阻止自动发布和激活。当前报告距今 {round(age_seconds / 3600, 2)} 小时。",
                "generated_at": latest.get("generated_at"),
                "gate": gate,
                "metrics": metrics,
                "age_seconds": round(age_seconds, 2),
                "max_age_hours": effective_max_age_hours,
            }

        if not bool(gate.get("passed")):
            return {
                "ready": False,
                "reason": "evaluation_gate_failed",
                "message": "最新评估未通过质量门禁，已阻止自动发布和激活。",
                "generated_at": latest.get("generated_at"),
                "gate": gate,
                "metrics": metrics,
                "age_seconds": round(age_seconds, 2),
                "max_age_hours": effective_max_age_hours,
            }

        return {
            "ready": True,
            "reason": "evaluation_gate_passed",
            "message": "最新评估通过部署门禁，可以继续自动发布和激活。",
            "generated_at": latest.get("generated_at"),
            "gate": gate,
            "metrics": metrics,
            "age_seconds": round(age_seconds, 2),
            "max_age_hours": effective_max_age_hours,
        }

    async def _load_documents(self, tenant_id: str, *, sample_limit: int) -> list[dict[str, Any]]:
        primary_rows = await self.db.execute(
            select(Document.id, Document.title, DocumentChunk.content)
            .join(DocumentChunk, DocumentChunk.doc_id == Document.id)
            .where(Document.tenant_id == tenant_id, Document.status == "ready")
            .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
            .limit(max(sample_limit * 8, 50))
        )
        primary_grouped = self._group_documents(primary_rows.all(), sample_limit=sample_limit, exclude_synthetic=True)
        if primary_grouped:
            return primary_grouped

        fallback_rows = await self.db.execute(
            select(Document.id, Document.title, DocumentChunk.content)
            .join(DocumentChunk, DocumentChunk.doc_id == Document.id)
            .where(Document.tenant_id == tenant_id, Document.status == "ready")
            .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
            .limit(max(sample_limit * 4, 20))
        )
        fallback_grouped = self._group_documents(fallback_rows.all(), sample_limit=sample_limit, exclude_synthetic=False)
        if fallback_grouped and any(not self._is_synthetic_eval_title(item.get("title")) for item in fallback_grouped):
            return fallback_grouped
        return self._build_seed_documents(sample_limit)

    def _group_documents(self, rows: list[tuple], *, sample_limit: int, exclude_synthetic: bool) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for doc_id, title, content in rows:
            if exclude_synthetic and self._is_synthetic_eval_title(title):
                continue
            item = grouped.setdefault(doc_id, {"id": doc_id, "title": title, "chunks": []})
            item["chunks"].append({"content": content})
            if len(grouped) >= sample_limit and len(item["chunks"]) >= 1:
                continue
        return list(grouped.values())[: max(sample_limit, 1)]

    def _is_synthetic_eval_title(self, title: str | None) -> bool:
        normalized = str(title or "").strip().lower()
        if not normalized:
            return False
        return bool(
            re.match(r"^(smoke_|tmp_|test_|sample_)", normalized)
            or normalized.endswith((".tmp.csv", ".sample.csv"))
        )

    def _build_gate(self, metrics: dict[str, Any], dataset_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        thresholds = self._resolve_metric_thresholds(metrics.get("_meta") or {})
        checks = [
            ("faithfulness", float(metrics.get("faithfulness", 0.0) or 0.0), thresholds["faithfulness"]),
            ("answer_relevancy", float(metrics.get("answer_relevancy", 0.0) or 0.0), thresholds["answer_relevancy"]),
            ("context_precision", float(metrics.get("context_precision", 0.0) or 0.0), thresholds["context_precision"]),
            ("context_recall", float(metrics.get("context_recall", 0.0) or 0.0), thresholds["context_recall"]),
        ]
        failures = [
            {
                "metric": name,
                "actual": round(actual, 4),
                "threshold": threshold,
                "delta": round(actual - threshold, 4),
            }
            for name, actual, threshold in checks
            if actual < threshold
        ]
        meta = metrics.get("_meta") or {}
        real_mode_ok = True
        real_mode_reason = None
        if settings.ci_gate_require_real_ragas and not bool(meta.get("real_mode")):
            real_mode_ok = False
            real_mode_reason = "ci_gate_require_real_ragas=true but evaluation is not in real_mode"
            failures.append(
                {
                    "metric": "real_mode",
                    "actual": bool(meta.get("real_mode")),
                    "threshold": True,
                    "delta": None,
                }
            )
        summary = dataset_summary if isinstance(dataset_summary, dict) else {}
        dataset_size = int(summary.get("dataset_size", 0) or 0)
        unique_doc_count = int(summary.get("unique_doc_count", 0) or 0)
        difficulty_counts = summary.get("difficulty_counts") if isinstance(summary.get("difficulty_counts"), dict) else {}
        task_type_counts = summary.get("task_type_counts") if isinstance(summary.get("task_type_counts"), dict) else {}
        difficulty_bucket_count = sum(1 for value in difficulty_counts.values() if int(value or 0) > 0)
        task_type_bucket_count = sum(1 for value in task_type_counts.values() if int(value or 0) > 0)
        grounded_sample_count = int(summary.get("grounded_sample_count", 0) or 0)
        compare_sample_count = int(summary.get("compare_sample_count", 0) or 0)
        follow_up_sample_count = int(summary.get("follow_up_sample_count", 0) or 0)
        avg_context_length = float(summary.get("avg_context_length", 0.0) or 0.0)
        if summary:
            if dataset_size < settings.ci_gate_min_eval_dataset_size:
                failures.append(
                    {
                        "metric": "dataset_size",
                        "actual": dataset_size,
                        "threshold": settings.ci_gate_min_eval_dataset_size,
                        "delta": dataset_size - settings.ci_gate_min_eval_dataset_size,
                    }
                )
            if unique_doc_count < settings.ci_gate_min_eval_unique_docs:
                failures.append(
                    {
                        "metric": "unique_doc_count",
                        "actual": unique_doc_count,
                        "threshold": settings.ci_gate_min_eval_unique_docs,
                        "delta": unique_doc_count - settings.ci_gate_min_eval_unique_docs,
                    }
                )
            if difficulty_bucket_count < settings.ci_gate_min_eval_difficulty_buckets:
                failures.append(
                    {
                        "metric": "difficulty_buckets",
                        "actual": difficulty_bucket_count,
                        "threshold": settings.ci_gate_min_eval_difficulty_buckets,
                        "delta": difficulty_bucket_count - settings.ci_gate_min_eval_difficulty_buckets,
                    }
                )
            if grounded_sample_count < settings.ci_gate_min_eval_grounded_samples:
                failures.append(
                    {
                        "metric": "grounded_sample_count",
                        "actual": grounded_sample_count,
                        "threshold": settings.ci_gate_min_eval_grounded_samples,
                        "delta": grounded_sample_count - settings.ci_gate_min_eval_grounded_samples,
                    }
                )
            if task_type_bucket_count < settings.ci_gate_min_eval_task_type_buckets:
                failures.append(
                    {
                        "metric": "task_type_buckets",
                        "actual": task_type_bucket_count,
                        "threshold": settings.ci_gate_min_eval_task_type_buckets,
                        "delta": task_type_bucket_count - settings.ci_gate_min_eval_task_type_buckets,
                    }
                )
            if compare_sample_count < settings.ci_gate_min_eval_compare_samples:
                failures.append(
                    {
                        "metric": "compare_sample_count",
                        "actual": compare_sample_count,
                        "threshold": settings.ci_gate_min_eval_compare_samples,
                        "delta": compare_sample_count - settings.ci_gate_min_eval_compare_samples,
                    }
                )
            if follow_up_sample_count < settings.ci_gate_min_eval_follow_up_samples:
                failures.append(
                    {
                        "metric": "follow_up_sample_count",
                        "actual": follow_up_sample_count,
                        "threshold": settings.ci_gate_min_eval_follow_up_samples,
                        "delta": follow_up_sample_count - settings.ci_gate_min_eval_follow_up_samples,
                    }
                )
            if avg_context_length < settings.ci_gate_min_eval_avg_context_length:
                failures.append(
                    {
                        "metric": "avg_context_length",
                        "actual": round(avg_context_length, 2),
                        "threshold": settings.ci_gate_min_eval_avg_context_length,
                        "delta": round(avg_context_length - settings.ci_gate_min_eval_avg_context_length, 2),
                    }
                )
        return {
            "passed": not failures and real_mode_ok,
            "failures": failures,
            "real_mode_required": settings.ci_gate_require_real_ragas,
            "real_mode_ok": real_mode_ok,
            "real_mode_reason": real_mode_reason,
            "dataset_summary": summary,
            "thresholds": thresholds,
        }

    def _summarize_dataset(self, dataset: list[dict[str, Any]]) -> dict[str, Any]:
        unique_docs: set[str] = set()
        difficulty_counts: dict[str, int] = {}
        task_type_counts: dict[str, int] = {}
        context_lengths: list[int] = []
        grounded_sample_count = 0
        compare_sample_count = 0
        follow_up_sample_count = 0
        for item in dataset:
            for doc_id in item.get("context_doc_ids") or []:
                if doc_id:
                    unique_docs.add(str(doc_id))
            difficulty = str(item.get("difficulty") or "unknown")
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1
            task_type = str(item.get("task_type") or "unknown")
            task_type_counts[task_type] = task_type_counts.get(task_type, 0) + 1
            if difficulty == "grounded":
                grounded_sample_count += 1
            if task_type in {"compare", "cross_doc_compare"}:
                compare_sample_count += 1
            if task_type == "follow_up":
                follow_up_sample_count += 1
            context_text = " ".join(item.get("contexts") or [])
            context_lengths.append(len(context_text))
        avg_context_length = round(sum(context_lengths) / len(context_lengths), 2) if context_lengths else 0.0
        return {
            "dataset_size": len(dataset),
            "unique_doc_count": len(unique_docs),
            "difficulty_counts": difficulty_counts,
            "task_type_counts": task_type_counts,
            "grounded_sample_count": grounded_sample_count,
            "compare_sample_count": compare_sample_count,
            "follow_up_sample_count": follow_up_sample_count,
            "avg_context_length": avg_context_length,
        }

    def _build_seed_documents(self, sample_limit: int) -> list[dict[str, Any]]:
        seeds = [
            {
                "id": "seed-budget",
                "title": "预算管理办法",
                "chunks": [
                    {
                        "content": (
                            "预算编制应当坚持统筹安排、量入为出。"
                            "各部门提交预算申请前，应当完成项目必要性说明和资金测算。"
                            "预算方案经财务部门复核后，报分管负责人审批。"
                        )
                    }
                ],
            },
            {
                "id": "seed-travel",
                "title": "差旅审批制度",
                "chunks": [
                    {
                        "content": (
                            "员工出差前应当在系统中提交差旅申请。"
                            "申请内容包括出差事由、地点、时间和预计费用。"
                            "直属负责人审批通过后，方可预订交通和住宿。"
                        )
                    }
                ],
            },
            {
                "id": "seed-procurement",
                "title": "采购管理制度",
                "chunks": [
                    {
                        "content": (
                            "采购申请需写明采购事项、供应商范围和预算来源。"
                            "单笔采购金额超过五万元时，需组织不少于三家供应商比价。"
                            "采购结果需留存评审记录和合同文本。"
                        )
                    }
                ],
            },
            {
                "id": "seed-compliance",
                "title": "合规审查流程",
                "chunks": [
                    {
                        "content": (
                            "制度文件发布前必须完成合规审查。"
                            "法务人员重点核对授权依据、审批链路和监管要求。"
                            "若存在高风险条款，应退回起草部门修订后再提交。"
                        )
                    }
                ],
            },
            {
                "id": "seed-reimbursement",
                "title": "报销管理规范",
                "chunks": [
                    {
                        "content": (
                            "报销申请应在业务发生后十个工作日内提交。"
                            "申请人需上传发票、行程单和付款凭证。"
                            "若票据不完整，财务应一次性退回并说明原因。"
                        )
                    }
                ],
            },
        ]
        return seeds[: max(sample_limit, 1)]

    def _resolve_metric_thresholds(self, meta: dict[str, Any]) -> dict[str, float]:
        mode = str(meta.get("mode") or "").strip().lower()
        if mode == "ragas_ollama":
            return {
                "faithfulness": settings.ci_gate_min_faithfulness_ragas_ollama,
                "answer_relevancy": settings.ci_gate_min_answer_relevancy_ragas_ollama,
                "context_precision": settings.ci_gate_min_context_precision_ragas_ollama,
                "context_recall": settings.ci_gate_min_context_recall_ragas_ollama,
            }
        return {
            "faithfulness": settings.ci_gate_min_faithfulness,
            "answer_relevancy": settings.ci_gate_min_answer_relevancy,
            "context_precision": settings.ci_gate_min_context_precision,
            "context_recall": settings.ci_gate_min_context_recall,
        }

    def _normalize_saved_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "metrics" in payload:
            metrics = payload.get("metrics") or {}
            return {
                "metrics": metrics,
                "gate": payload.get("gate")
                or self._build_gate(metrics, dataset_summary=(payload.get("generated_from") or {}).get("dataset_summary")),
                "generated_at": payload.get("generated_at"),
                "generated_from": payload.get("generated_from") or {},
                "dataset_size": payload.get("dataset_size", metrics.get("sample_count", 0)),
            }

        # Legacy report shape: the whole JSON file is metrics only.
        metrics = payload
        return {
            "metrics": metrics,
            "gate": self._build_gate(metrics),
            "generated_at": None,
            "generated_from": {"tenant_id": None, "sample_limit": None, "document_count": None, "legacy_report": True},
            "dataset_size": metrics.get("sample_count", 0),
        }

    def _build_drift_summary(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if len(items) < 2:
            return {"available": False, "reason": "insufficient_history"}

        latest = items[0] if isinstance(items[0], dict) else {}
        previous = items[1] if isinstance(items[1], dict) else {}
        latest_metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
        previous_metrics = previous.get("metrics") if isinstance(previous.get("metrics"), dict) else {}
        latest_gate = latest.get("gate") if isinstance(latest.get("gate"), dict) else {}
        previous_gate = previous.get("gate") if isinstance(previous.get("gate"), dict) else {}
        latest_meta = latest_metrics.get("_meta") if isinstance(latest_metrics.get("_meta"), dict) else {}
        previous_meta = previous_metrics.get("_meta") if isinstance(previous_metrics.get("_meta"), dict) else {}
        latest_dataset_summary = (
            latest_gate.get("dataset_summary") if isinstance(latest_gate.get("dataset_summary"), dict) else {}
        )
        previous_dataset_summary = (
            previous_gate.get("dataset_summary") if isinstance(previous_gate.get("dataset_summary"), dict) else {}
        )

        metric_deltas: dict[str, float] = {}
        for metric_name in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
            latest_value = self._coerce_float(latest_metrics.get(metric_name))
            previous_value = self._coerce_float(previous_metrics.get(metric_name))
            if latest_value is None or previous_value is None:
                continue
            metric_deltas[metric_name] = round(latest_value - previous_value, 4)

        latest_dataset_size = self._coerce_int(latest.get("dataset_size"))
        previous_dataset_size = self._coerce_int(previous.get("dataset_size"))
        latest_unique_docs = self._coerce_int(latest_dataset_summary.get("unique_doc_count"))
        previous_unique_docs = self._coerce_int(previous_dataset_summary.get("unique_doc_count"))

        return {
            "available": True,
            "latest_generated_at": latest.get("generated_at"),
            "previous_generated_at": previous.get("generated_at"),
            "metrics": metric_deltas,
            "gate_changed": bool(latest_gate.get("passed")) != bool(previous_gate.get("passed")),
            "real_mode_changed": bool(latest_meta.get("real_mode")) != bool(previous_meta.get("real_mode")),
            "dataset_size_delta": None
            if latest_dataset_size is None or previous_dataset_size is None
            else latest_dataset_size - previous_dataset_size,
            "unique_doc_count_delta": None
            if latest_unique_docs is None or previous_unique_docs is None
            else latest_unique_docs - previous_unique_docs,
        }

    def _coerce_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_int(self, value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_iso_datetime(self, value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    async def _notify_progress(
        self,
        callback: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None,
        stage: str,
        payload: dict[str, Any],
    ) -> None:
        if callback is None:
            return
        result = callback(stage, payload)
        if result is not None:
            await result

    async def _persist_history_snapshot(self, tenant_id: str, payload: dict[str, Any]) -> None:
        if self.redis is None:
            return
        key = self._history_key(tenant_id)
        row = json.dumps(payload, ensure_ascii=False)
        if hasattr(self.redis, "lpush"):
            await self.redis.lpush(key, row)
        else:
            await self.redis.rpush(key, row)
        await self.redis.ltrim(key, 0, 199)
        await self.redis.expire(key, 30 * 24 * 3600)

    def _history_key(self, tenant_id: str) -> str:
        return f"metrics:evaluation:history:{tenant_id}"
