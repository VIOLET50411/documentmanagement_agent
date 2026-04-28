"""Delivery gap report service for remaining enterprise/financial targets."""

from __future__ import annotations

from app.config import settings
from app.services.security_policy_service import SecurityPolicyService


class DeliveryGapService:
    """Generate a structured progress and gap report for admins."""

    async def build_report(self) -> dict:
        policy_eval = SecurityPolicyService().evaluate()
        profile = policy_eval.get("profile")

        completed = [
            "runtime_v2_only",
            "runtime_task_store",
            "runtime_tool_registry_and_gate",
            "runtime_sse_replay_resume",
            "runtime_tool_decision_audit_dual_write",
            "scheduled_runtime_maintenance",
            "full_llmops_regression_gating",
        ]
        in_progress = []
        pending = []

        if profile == "financial" and not settings.clamav_enabled:
            pending.append("clamav_enforced_scan")
        elif profile != "financial":
            completed.append("clamav_enforced_scan")
        if not settings.guardrails_enabled:
            pending.append("guardrail_sidecar_hard_enforcement")

        if policy_eval.get("compliant"):
            completed.append("financial_grade_policy_pack")
        else:
            pending.append("financial_grade_policy_pack")

        # Non-LLM stage still keeps evaluation of true faithfulness as pending.
        pending.extend(
            [
                "ragas_faithfulness_pipeline_with_real_llm",
            ]
        )
        completed.append("advanced_dlp_and_watermark_forensics")

        return {
            "target_profile": profile or "enterprise",
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
                "金融级安全与完整 LLMOps 仍需真实模型与策略侧车接入。",
                f"当前安全策略档位: {policy_eval.get('profile')}",
            ],
            "security_policy": policy_eval,
        }
