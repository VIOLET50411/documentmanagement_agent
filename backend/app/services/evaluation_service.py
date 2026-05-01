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
        await self._notify_progress(
            progress_callback,
            "evaluating",
            {"tenant_id": tenant_id, "dataset_size": len(dataset), "document_count": len(documents)},
        )
        metrics = await self.runner.evaluate(dataset=dataset)
        gate = self._build_gate(metrics)

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
        return self._group_documents(fallback_rows.all(), sample_limit=sample_limit, exclude_synthetic=False)

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

    def _build_gate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        checks = [
            ("faithfulness", float(metrics.get("faithfulness", 0.0) or 0.0), settings.ci_gate_min_faithfulness),
            ("answer_relevancy", float(metrics.get("answer_relevancy", 0.0) or 0.0), settings.ci_gate_min_answer_relevancy),
            ("context_precision", float(metrics.get("context_precision", 0.0) or 0.0), settings.ci_gate_min_context_precision),
            ("context_recall", float(metrics.get("context_recall", 0.0) or 0.0), settings.ci_gate_min_context_recall),
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
        return {
            "passed": not failures and real_mode_ok,
            "failures": failures,
            "real_mode_required": settings.ci_gate_require_real_ragas,
            "real_mode_ok": real_mode_ok,
            "real_mode_reason": real_mode_reason,
        }

    def _normalize_saved_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "metrics" in payload:
            metrics = payload.get("metrics") or {}
            return {
                "metrics": metrics,
                "gate": payload.get("gate") or self._build_gate(metrics),
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
