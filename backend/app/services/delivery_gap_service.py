from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.llm_training import LLMModelRegistry, LLMTrainingJob
from app.services.llm_training_service import LLMTrainingService
from app.services.security_policy_service import SecurityPolicyService


class DeliveryGapService:
    """Generate a structured progress and gap report for admins."""

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    async def build_report(self, tenant_id: str | None = None) -> dict[str, Any]:
        policy_eval = SecurityPolicyService().evaluate()
        profile = policy_eval.get("profile")
        effective_tenant = (tenant_id or "default").strip() or "default"

        completed = [
            "runtime_v2_only",
            "runtime_task_store",
            "runtime_tool_registry_and_gate",
            "runtime_sse_replay_resume",
            "runtime_tool_decision_audit_dual_write",
            "scheduled_runtime_maintenance",
        ]
        in_progress: list[str] = []
        pending: list[str] = []

        if profile == "financial" and not settings.clamav_enabled:
            pending.append("clamav_enforced_scan")
        else:
            completed.append("clamav_enforced_scan")

        if not settings.guardrails_enabled:
            pending.append("guardrail_sidecar_hard_enforcement")
        else:
            completed.append("guardrail_sidecar_hard_enforcement")

        if policy_eval.get("compliant"):
            completed.append("financial_grade_policy_pack")
        else:
            pending.append("financial_grade_policy_pack")

        ragas_status = self._evaluate_ragas_status(effective_tenant)
        if ragas_status["real_mode"]:
            completed.extend(["full_llmops_regression_gating", "ragas_faithfulness_pipeline_with_real_llm"])
        else:
            pending.extend(["full_llmops_regression_gating", "ragas_faithfulness_pipeline_with_real_llm"])

        publish_status = await self._evaluate_training_publish_status(effective_tenant)
        if publish_status["pipeline_ready"]:
            completed.append("training_artifact_publish_pipeline")
        else:
            pending.append("training_artifact_publish_pipeline")
        if publish_status["publishable_base_aligned"]:
            completed.append("training_publishable_base_model_alignment")
        else:
            pending.append("training_publishable_base_model_alignment")

        completed.append("advanced_dlp_and_watermark_forensics")

        return {
            "target_profile": profile or "enterprise",
            "tenant_id": effective_tenant,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
            "summary": {
                "completed_count": len(completed),
                "in_progress_count": len(in_progress),
                "pending_count": len(pending),
            },
            "notes": [
                "当前已具备企业级可运行底座，但距离完整训练上线闭环仍有差距。",
                ragas_status["note"],
                publish_status["note"],
                f"当前安全策略档位: {policy_eval.get('profile')}",
            ],
            "security_policy": policy_eval,
            "ragas_status": ragas_status,
            "training_publish_status": publish_status,
        }

    def _evaluate_ragas_status(self, tenant_id: str) -> dict[str, Any]:
        report_path = Path(settings.docmind_reports_dir) / f"evaluation_{tenant_id}.json"
        if not report_path.exists():
            return {
                "real_mode": False,
                "mode": None,
                "report_path": str(report_path),
                "note": "真实 Ragas 评估报告尚未生成。",
            }

        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            metrics = payload.get("metrics") if isinstance(payload, dict) else {}
            meta = metrics.get("_meta") if isinstance(metrics, dict) else {}
            real_mode = bool(meta.get("real_mode"))
            mode = str(meta.get("mode") or "")
            if real_mode:
                return {
                    "real_mode": True,
                    "mode": mode or "ragas_api",
                    "report_path": str(report_path),
                    "note": f"真实 Ragas 评估已跑通，当前模式: {mode or 'ragas_api'}。",
                }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        return {
            "real_mode": False,
            "mode": None,
            "report_path": str(report_path),
            "note": "评估报告已存在，但尚未确认真实 Ragas 模式。",
        }

    async def _evaluate_training_publish_status(self, tenant_id: str) -> dict[str, Any]:
        publish_enabled = bool(settings.llm_training_publish_enabled)
        publish_command = str(settings.llm_training_publish_command or "").strip()
        uses_ollama_cli = "ollama" in publish_command.lower()
        ollama_cli_available = True if not uses_ollama_cli else bool(shutil.which("ollama"))

        tiny_enabled = os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "false").lower() == "true"
        tiny_model = os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "sshleifer/tiny-gpt2").strip()
        export_merged_model = os.getenv("DOCMIND_TRAINING_EXPORT_MERGED_MODEL", "false").lower() == "true"
        supported_prefixes = LLMTrainingService.OLLAMA_ADAPTER_SUPPORTED_PREFIXES
        normalized_tiny = tiny_model.lower()
        publishable_base_aligned = (
            not tiny_enabled
            or export_merged_model
            or LLMTrainingService.supports_ollama_adapter_base_model(normalized_tiny)
        )
        publish_runtime_ready = publish_enabled and bool(publish_command) and ollama_cli_available
        evidence = await self._load_training_publish_evidence(tenant_id)
        pipeline_ready = publish_runtime_ready and evidence["published_model_present"]

        if pipeline_ready and publishable_base_aligned:
            note = "训练产物发布链路已完成，存在真实已发布模型证据。"
        elif publish_runtime_ready and evidence["executed_training_present"]:
            note = "训练执行与发布运行条件已就绪，且存在真实训练产物，但尚无已发布模型证据。"
        elif publish_runtime_ready and publishable_base_aligned:
            note = "训练发布运行条件与基座对齐均已满足，但尚未观察到真实训练产物或已发布模型证据。"
        elif publish_enabled and bool(publish_command) and not ollama_cli_available:
            note = "训练产物发布命令已配置，但当前运行环境缺少 ollama CLI。"
        elif publish_enabled and bool(publish_command):
            note = (
                f"训练产物可执行发布命令，但当前 dev tiny model 为 {tiny_model}，"
                "仍未满足当前发布策略要求。"
            )
        elif publish_enabled:
            note = "训练产物发布已启用，但缺少可执行的发布命令配置。"
        else:
            note = "训练产物发布开关尚未启用。"

        return {
            "pipeline_ready": pipeline_ready,
            "publish_enabled": publish_enabled,
            "publish_command_configured": bool(publish_command),
            "publishable_base_aligned": publishable_base_aligned,
            "publish_runtime_ready": publish_runtime_ready,
            "ollama_cli_required": uses_ollama_cli,
            "ollama_cli_available": ollama_cli_available,
            "dev_tiny_model_enabled": tiny_enabled,
            "dev_tiny_model": tiny_model if tiny_enabled else None,
            "export_merged_model": export_merged_model,
            "supported_prefixes": list(supported_prefixes),
            **evidence,
            "note": note,
        }

    async def _load_training_publish_evidence(self, tenant_id: str) -> dict[str, Any]:
        evidence = {
            "executed_training_present": False,
            "published_model_present": False,
            "latest_training_job_id": None,
            "latest_model_id": None,
        }
        if self.db is None:
            return await self._load_training_publish_evidence_from_artifacts(tenant_id, evidence)

        jobs = (
            await self.db.execute(
                select(LLMTrainingJob)
                .where(LLMTrainingJob.tenant_id == tenant_id)
                .order_by(LLMTrainingJob.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        for job in jobs:
            if evidence["latest_training_job_id"] is None:
                evidence["latest_training_job_id"] = job.id
            payload = self._load_json(job.result_json)
            executor_meta = payload.get("executor_metadata") if isinstance(payload.get("executor_metadata"), dict) else {}
            if str(executor_meta.get("mode") or "").strip().lower() == "executed":
                evidence["executed_training_present"] = True
                break

        models = (
            await self.db.execute(
                select(LLMModelRegistry)
                .where(LLMModelRegistry.tenant_id == tenant_id)
                .order_by(LLMModelRegistry.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        for model in models:
            if evidence["latest_model_id"] is None:
                evidence["latest_model_id"] = model.id
            metrics = self._load_json(model.metrics_json)
            publish_result = metrics.get("publish_result") if isinstance(metrics.get("publish_result"), dict) else {}
            if model.status in {"published", "active"} or bool(model.is_active) or bool(publish_result.get("published")):
                evidence["published_model_present"] = True
                break

        if not evidence["executed_training_present"] or not evidence["published_model_present"]:
            evidence = await self._load_training_publish_evidence_from_artifacts(tenant_id, evidence)
        return evidence

    async def _load_training_publish_evidence_from_artifacts(
        self,
        tenant_id: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(
            evidence
            or {
                "executed_training_present": False,
                "published_model_present": False,
                "latest_training_job_id": None,
                "latest_model_id": None,
            }
        )
        tenant_root = Path(settings.docmind_reports_dir) / settings.llm_training_artifacts_subdir / tenant_id
        if not tenant_root.exists():
            return payload

        published_models = await self._load_published_model_names()
        artifact_dirs = sorted(
            (path for path in tenant_root.iterdir() if path.is_dir()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for artifact_dir in artifact_dirs:
            if payload["latest_training_job_id"] is None:
                payload["latest_training_job_id"] = artifact_dir.name

            result_payload = self._load_json_path(artifact_dir / "training_result.json")
            metadata = result_payload.get("executor_metadata") if isinstance(result_payload.get("executor_metadata"), dict) else {}
            if metadata.get("mode") == "executed":
                payload["executed_training_present"] = True

            request_payload = self._load_json_path(artifact_dir / "training_request.json")
            target_model_name = str(
                request_payload.get("target_model_name")
                or result_payload.get("target_model_name")
                or ""
            ).strip()
            matched_name = self._match_published_model_name(target_model_name, published_models)
            if matched_name:
                payload["published_model_present"] = True
                payload["latest_model_id"] = matched_name

            if payload["executed_training_present"] and payload["published_model_present"]:
                break
        return payload

    async def _load_published_model_names(self) -> set[str]:
        candidates: list[str] = []
        for raw_base in (
            str(settings.llm_enterprise_api_base_url or "").strip(),
            str(settings.llm_api_base_url or "").strip(),
            "http://ollama:11434",
        ):
            if not raw_base:
                continue
            normalized = raw_base.rstrip("/")
            candidates.append(normalized)
            if normalized.endswith("/v1"):
                candidates.append(normalized[:-3])

        seen: set[str] = set()
        published: set[str] = set()
        timeout = httpx.Timeout(8.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for base in candidates:
                if not base or base in seen:
                    continue
                seen.add(base)
                for path in ("/v1/models", "/api/tags"):
                    url = f"{base}{path}"
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                    except httpx.HTTPError:
                        continue
                    try:
                        data = response.json()
                    except ValueError:
                        continue
                    if path == "/v1/models":
                        for item in data.get("data") or []:
                            model_name = str(item.get("id") or "").strip()
                            if model_name:
                                published.add(model_name)
                    else:
                        for item in data.get("models") or []:
                            for key in ("name", "model"):
                                model_name = str(item.get(key) or "").strip()
                                if model_name:
                                    published.add(model_name)
                if published:
                    break
        return published

    def _load_json_path(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _match_published_model_name(self, target_model_name: str, published_models: set[str]) -> str | None:
        normalized = str(target_model_name or "").strip()
        if not normalized:
            return None
        if normalized in published_models:
            return normalized
        for candidate in (f"{normalized}:latest", f"{normalized}:default"):
            if candidate in published_models:
                return candidate
        return None

    def _load_json(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
