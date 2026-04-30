"""Delivery gap report service for remaining enterprise/financial targets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.security_policy_service import SecurityPolicyService


class DeliveryGapService:
    """Generate a structured progress and gap report for admins."""

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

        publish_status = self._evaluate_training_publish_status()
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
                "当前阶段为非 LLM 优先，已达企业可运行基线。",
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
            "note": "评估报告存在，但尚未确认真实 Ragas 模式。",
        }

    def _evaluate_training_publish_status(self) -> dict[str, Any]:
        publish_enabled = bool(settings.llm_training_publish_enabled)
        publish_command = bool((settings.llm_training_publish_command or "").strip())
        tiny_enabled = os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "false").lower() == "true"
        tiny_model = os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL", "sshleifer/tiny-gpt2").strip()
        supported_prefixes = ("llama", "mistral", "gemma")
        normalized_tiny = tiny_model.lower()
        publishable_base_aligned = not tiny_enabled or any(prefix in normalized_tiny for prefix in supported_prefixes)
        pipeline_ready = publish_enabled and publish_command

        if pipeline_ready and publishable_base_aligned:
            note = "训练产物发布链路已具备自动发布条件。"
        elif pipeline_ready:
            note = f"训练产物可执行发布命令，但当前 dev tiny model 为 {tiny_model}，仍不满足 Ollama adapter 发布族要求。"
        elif publish_enabled:
            note = "训练产物发布已启用，但缺少可执行的发布命令配置。"
        else:
            note = "训练产物发布开关未启用。"

        return {
            "pipeline_ready": pipeline_ready,
            "publish_enabled": publish_enabled,
            "publish_command_configured": publish_command,
            "publishable_base_aligned": publishable_base_aligned,
            "dev_tiny_model_enabled": tiny_enabled,
            "dev_tiny_model": tiny_model if tiny_enabled else None,
            "supported_prefixes": list(supported_prefixes),
            "note": note,
        }
