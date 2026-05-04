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
from app.services.mobile_oauth_service import MobileOAuthService
from app.services.push_notification_service import PushNotificationService
from app.services.evaluation_service import EvaluationService
from app.services.security_policy_service import SecurityPolicyService
from app.training.executor import describe_training_runtime


class DeliveryGapService:
    """Generate a structured progress and gap report for admins."""

    def __init__(self, db: AsyncSession | None = None, redis_client=None):
        self.db = db
        self.redis = redis_client

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
        if policy_eval.get("blocking"):
            pending.append("security_fail_closed_linkage")
        else:
            completed.append("security_fail_closed_linkage")

        ragas_status = self._evaluate_ragas_status(effective_tenant)
        if ragas_status["real_mode"]:
            completed.extend(["full_llmops_regression_gating", "ragas_faithfulness_pipeline_with_real_llm"])
        else:
            pending.extend(["full_llmops_regression_gating", "ragas_faithfulness_pipeline_with_real_llm"])

        training_runtime = describe_training_runtime()
        if training_runtime.get("ready"):
            completed.append("training_executor_runtime_ready")
        else:
            pending.append("training_executor_runtime_ready")

        publish_status = await self._evaluate_training_publish_status(effective_tenant)
        if publish_status["pipeline_ready"]:
            completed.append("training_artifact_publish_pipeline")
        else:
            pending.append("training_artifact_publish_pipeline")
        if publish_status["publishable_base_aligned"]:
            completed.append("training_publishable_base_model_alignment")
        else:
            pending.append("training_publishable_base_model_alignment")

        deployment_gate_status = await self._evaluate_training_deployment_gate_status(effective_tenant)
        if deployment_gate_status["ready_for_activation"]:
            completed.append("training_deployment_gate_ready")
        else:
            pending.append("training_deployment_gate_ready")
        approval_status = await self._evaluate_training_manual_approval_status(effective_tenant)
        if approval_status["ready_for_activation"]:
            completed.append("training_manual_approval_gate")
        else:
            pending.append("training_manual_approval_gate")

        mobile_auth_status = MobileOAuthService(self.db).status(settings.effective_public_base_url)
        if mobile_auth_status["ready"]:
            completed.append("mobile_oauth_runtime_ready")
        else:
            pending.append("mobile_oauth_runtime_ready")

        miniapp_status = mobile_auth_status.get("miniapp") or {}
        if miniapp_status.get("ready"):
            completed.append("miniapp_oauth_bootstrap_ready")
        else:
            pending.append("miniapp_oauth_bootstrap_ready")

        push_status = await PushNotificationService(self.db, self.redis).get_health_summary(tenant_id=effective_tenant)
        if push_status["ready"]:
            completed.append("push_notification_runtime_ready")
        else:
            pending.append("push_notification_runtime_ready")

        push_providers = push_status.get("providers") if isinstance(push_status.get("providers"), dict) else {}
        if bool(push_providers.get("wechat", {}).get("ready")):
            completed.append("wechat_push_provider_ready")
        else:
            pending.append("wechat_push_provider_ready")

        completed.append("advanced_dlp_and_watermark_forensics")
        blockers = self._build_blockers(
            tenant_id=effective_tenant,
            pending=pending,
            training_runtime=training_runtime,
            publish_status=publish_status,
            deployment_gate_status=deployment_gate_status,
            approval_status=approval_status,
            mobile_auth_status=mobile_auth_status,
            push_status=push_status,
        )
        external_blockers = [item for item in blockers if item.get("scope") == "external"]
        internal_blockers = [item for item in blockers if item.get("scope") != "external"]
        total_items = len(completed) + len(in_progress) + len(pending)
        completion_percent = round((len(completed) / total_items) * 100, 1) if total_items else 100.0

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
                "internal_blocker_count": len(internal_blockers),
                "external_blocker_count": len(external_blockers),
                "completion_percent": completion_percent,
            },
            "blockers": blockers,
            "external_blockers": external_blockers,
            "internal_blockers": internal_blockers,
            "notes": [
                "当前已具备企业级可运行底座，但距离完整训练上线闭环仍有差距。",
                ragas_status["note"],
                self._build_training_runtime_note(training_runtime),
                publish_status["note"],
                deployment_gate_status["note"],
                approval_status["note"],
                self._build_mobile_runtime_note(mobile_auth_status),
                self._build_push_runtime_note(push_status),
                self._build_security_policy_note(policy_eval),
            ],
            "security_policy": policy_eval,
            "ragas_status": ragas_status,
            "training_runtime_status": training_runtime,
            "training_publish_status": publish_status,
            "training_deployment_gate_status": deployment_gate_status,
            "training_manual_approval_status": approval_status,
            "mobile_auth_status": mobile_auth_status,
            "push_runtime_status": push_status,
        }

    def _build_security_policy_note(self, policy: dict[str, Any]) -> str:
        profile = str(policy.get("profile") or "enterprise")
        status = str(policy.get("status") or "unknown")
        missing = policy.get("missing_control_ids") if isinstance(policy.get("missing_control_ids"), list) else []
        if status == "compliant":
            return f"当前安全策略档位: {profile}，所有要求控制项均已满足。"
        if status == "blocked":
            return f"当前安全策略档位: {profile}，存在阻断项: {', '.join(str(item) for item in missing[:6]) or 'unknown'}。"
        return f"当前安全策略档位: {profile}，存在待收口控制项: {', '.join(str(item) for item in missing[:6]) or 'unknown'}。"

    def _build_training_runtime_note(self, runtime: dict[str, Any]) -> str:
        if runtime.get("ready"):
            provider = runtime.get("resolved_provider") or runtime.get("configured_provider")
            source = runtime.get("command_source") or "configured"
            return f"训练执行器已就绪，当前 provider={provider}，命令来源={source}。"

        reason = str(runtime.get("reason") or "训练执行器尚未就绪").strip()
        missing = runtime.get("missing_dependencies") if isinstance(runtime.get("missing_dependencies"), list) else []
        if missing:
            return f"{reason}，缺少依赖: {', '.join(str(item) for item in missing)}。"
        return f"{reason}。"

    def _build_mobile_runtime_note(self, status: dict[str, Any]) -> str:
        if status.get("ready"):
            miniapp = status.get("miniapp") if isinstance(status.get("miniapp"), dict) else {}
            if miniapp.get("ready"):
                return "移动 OAuth 与小程序 bootstrap 均已就绪。"
            return "移动 OAuth 已就绪，但小程序 bootstrap 仍需补齐客户端或回调配置。"
        issues = status.get("issues") if isinstance(status.get("issues"), list) else []
        return f"移动 OAuth 尚未完全就绪，问题: {', '.join(str(item) for item in issues) or 'unknown'}。"

    def _build_push_runtime_note(self, status: dict[str, Any]) -> str:
        providers = status.get("providers") if isinstance(status.get("providers"), dict) else {}
        missing = [
            provider
            for provider in ("wechat",)
            if not bool(providers.get(provider, {}).get("ready"))
        ]
        if status.get("ready") and not missing:
            return "推送运行态与多端 provider 均已就绪。"
        if status.get("ready"):
            return f"推送主链路已就绪，但以下 provider 仍待补齐: {', '.join(missing)}。"
        issues = status.get("issues") if isinstance(status.get("issues"), list) else []
        return f"推送运行态未完全就绪，问题: {', '.join(str(item) for item in issues) or 'unknown'}。"

    def _build_blockers(
        self,
        *,
        tenant_id: str,
        pending: list[str],
        training_runtime: dict[str, Any],
        publish_status: dict[str, Any],
        deployment_gate_status: dict[str, Any],
        approval_status: dict[str, Any],
        mobile_auth_status: dict[str, Any],
        push_status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        pending_set = set(pending)

        if "training_executor_runtime_ready" in pending_set:
            blockers.append(
                {
                    "id": "training_executor_runtime_ready",
                    "title": "训练执行器运行时未就绪",
                    "scope": "internal",
                    "category": "training",
                    "severity": "high",
                    "tenant_id": tenant_id,
                    "ready": bool(training_runtime.get("ready")),
                    "reason": str(training_runtime.get("reason") or "training_runtime_not_ready"),
                    "missing_dependencies": list(training_runtime.get("missing_dependencies") or []),
                    "next_step": self._build_training_runtime_note(training_runtime),
                }
            )

        if "training_artifact_publish_pipeline" in pending_set or "training_publishable_base_model_alignment" in pending_set:
            blockers.append(
                {
                    "id": "training_publish_pipeline",
                    "title": "训练产物发布链路未完全收口",
                    "scope": "internal",
                    "category": "training_publish",
                    "severity": "high",
                    "tenant_id": tenant_id,
                    "publish_runtime_ready": bool(publish_status.get("publish_runtime_ready")),
                    "publishable_base_aligned": bool(publish_status.get("publishable_base_aligned")),
                    "evidence_ready": bool(publish_status.get("published_model_present")),
                    "reason": str(publish_status.get("note") or "training_publish_pipeline_pending"),
                    "next_step": str(publish_status.get("note") or "补齐训练发布运行条件与真实产物证据。"),
                }
            )

        if "training_deployment_gate_ready" in pending_set:
            blockers.append(
                {
                    "id": "training_deployment_gate_ready",
                    "title": "训练部署门禁未满足",
                    "scope": "internal",
                    "category": "deployment_gate",
                    "severity": "high",
                    "tenant_id": tenant_id,
                    "ready": bool(deployment_gate_status.get("ready_for_activation")),
                    "reason": str(deployment_gate_status.get("note") or "deployment_gate_blocked"),
                    "blocked_reason_samples": list(deployment_gate_status.get("blocked_reason_samples") or []),
                    "next_step": str(deployment_gate_status.get("note") or "先修复评估或门禁阻断项。"),
                }
            )

        if "training_manual_approval_gate" in pending_set:
            blockers.append(
                {
                    "id": "training_manual_approval_gate",
                    "title": "训练人工审批门未满足",
                    "scope": "internal",
                    "category": "approval",
                    "severity": "high",
                    "tenant_id": tenant_id,
                    "ready": bool(approval_status.get("ready_for_activation")),
                    "reason": str(approval_status.get("note") or "approval_pending"),
                    "pending_reason_samples": list(approval_status.get("pending_reason_samples") or []),
                    "next_step": str(approval_status.get("note") or "完成模型审批后再进入激活流程。"),
                }
            )

        if "mobile_oauth_runtime_ready" in pending_set or "miniapp_oauth_bootstrap_ready" in pending_set:
            blockers.append(
                {
                    "id": "mobile_oauth_runtime_ready",
                    "title": "移动端 OAuth 或小程序引导未完成",
                    "scope": "internal",
                    "category": "mobile_auth",
                    "severity": "medium",
                    "tenant_id": tenant_id,
                    "ready": bool(mobile_auth_status.get("ready")),
                    "issues": list(mobile_auth_status.get("issues") or []),
                    "miniapp_issues": list((mobile_auth_status.get("miniapp") or {}).get("issues") or []),
                    "next_step": self._build_mobile_runtime_note(mobile_auth_status),
                }
            )

        if "push_notification_runtime_ready" in pending_set:
            blockers.append(
                {
                    "id": "push_notification_runtime_ready",
                    "title": "推送运行态未完全就绪",
                    "scope": "internal",
                    "category": "push_runtime",
                    "severity": "high",
                    "tenant_id": tenant_id,
                    "ready": bool(push_status.get("ready")),
                    "issues": list(push_status.get("issues") or []),
                    "next_step": self._build_push_runtime_note(push_status),
                }
            )

        providers = push_status.get("providers") if isinstance(push_status.get("providers"), dict) else {}
        config_sources = push_status.get("configuration_sources") if isinstance(push_status.get("configuration_sources"), dict) else {}
        for provider_name in ("wechat",):
            pending_id = f"{provider_name}_push_provider_ready"
            if pending_id not in pending_set:
                continue
            provider_meta = providers.get(provider_name, {}) if isinstance(providers.get(provider_name), dict) else {}
            source_meta = config_sources.get(provider_name, {}) if isinstance(config_sources.get(provider_name), dict) else {}
            blockers.append(
                {
                    "id": pending_id,
                    "title": f"{provider_name.upper()} 推送 provider 待补齐",
                    "scope": "external",
                    "category": "push_provider",
                    "severity": "high",
                    "tenant_id": tenant_id,
                    "provider": provider_name,
                    "configured": bool(provider_meta.get("configured")),
                    "ready": bool(provider_meta.get("ready")),
                    "missing_env_vars": list(provider_meta.get("missing_env_vars") or []),
                    "required_env_vars": list(provider_meta.get("required_env_vars") or []),
                    "auth_mode": provider_meta.get("auth_mode") or provider_meta.get("auth_token_source"),
                    "configuration_source": source_meta.get("source"),
                    "configuration_detail": source_meta.get("detail"),
                    "next_step": str(provider_meta.get("next_step") or "补齐 provider 凭据并完成真机联调。"),
                }
            )

        return blockers

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

    async def _evaluate_training_deployment_gate_status(self, tenant_id: str) -> dict[str, Any]:
        evaluation_service = EvaluationService(self.db, self.redis, reports_dir=Path(settings.docmind_reports_dir))
        evaluation_readiness = await evaluation_service.assess_deployment_readiness(
            tenant_id,
            max_age_hours=settings.llm_training_eval_max_age_hours,
        )
        evaluation_summary = await evaluation_service.summarize_history(tenant_id, limit=10)
        deployment_summary = await self._load_training_deployment_summary(tenant_id)

        gate_counts = deployment_summary.get("deployment_gate_counts") if isinstance(deployment_summary.get("deployment_gate_counts"), dict) else {}
        blocked_recent = deployment_summary.get("recent_failures") if isinstance(deployment_summary.get("recent_failures"), list) else []
        blocked_reasons = [
            str(item.get("deployment_gate_reason") or "")
            for item in blocked_recent
            if item.get("deployment_gate_ready") is False and str(item.get("deployment_gate_reason") or "").strip()
        ]

        ready_for_activation = bool(evaluation_readiness.get("ready")) and (
            gate_counts.get("blocked", 0) == 0 or gate_counts.get("passed", 0) > 0
        )
        if ready_for_activation:
            note = "训练部署门禁已满足，最新评估与最近模型门禁记录均允许进入自动激活。"
        else:
            primary_reason = str(evaluation_readiness.get("reason") or "deployment_gate_blocked").strip()
            gate_reason = blocked_reasons[0] if blocked_reasons else primary_reason
            note = f"训练部署门禁尚未满足，当前阻塞原因: {gate_reason}。"

        return {
            "ready_for_activation": ready_for_activation,
            "evaluation_readiness": evaluation_readiness,
            "evaluation_summary": evaluation_summary,
            "deployment_summary": deployment_summary,
            "blocked_reason_samples": blocked_reasons[:5],
            "note": note,
        }

    async def _load_training_deployment_summary(self, tenant_id: str) -> dict[str, Any]:
        if self.db is None:
            return {
                "tenant_id": tenant_id,
                "deployment_gate_counts": {"passed": 0, "blocked": 0, "unknown": 0},
                "approval_counts": {"approved": 0, "pending": 0, "rejected": 0, "not_required": 0},
                "recent_failures": [],
            }
        service = LLMTrainingService(self.db, redis_client=self.redis, reports_dir=Path(settings.docmind_reports_dir))
        return await service.summarize_deployment(tenant_id, limit=20)

    async def _evaluate_training_manual_approval_status(self, tenant_id: str) -> dict[str, Any]:
        deployment_summary = await self._load_training_deployment_summary(tenant_id)
        approval_counts = deployment_summary.get("approval_counts") if isinstance(deployment_summary.get("approval_counts"), dict) else {}
        recent_failures = deployment_summary.get("recent_failures") if isinstance(deployment_summary.get("recent_failures"), list) else []
        pending_reasons = [
            str(item.get("approval_reason") or "")
            for item in recent_failures
            if item.get("approval_ready") is False and str(item.get("approval_reason") or "").strip()
        ]
        if not settings.llm_training_require_manual_approval:
            return {
                "required": False,
                "ready_for_activation": True,
                "approval_counts": approval_counts,
                "note": "当前未启用人工审批门。",
            }
        ready = approval_counts.get("pending", 0) == 0 and approval_counts.get("rejected", 0) == 0
        if ready:
            note = "人工审批门已满足，当前模型已具备进入激活流程的审批条件。"
        else:
            note = f"人工审批门尚未满足，当前阻塞原因: {(pending_reasons[0] if pending_reasons else 'approval_pending')}。"
        return {
            "required": True,
            "ready_for_activation": ready,
            "approval_counts": approval_counts,
            "pending_reason_samples": pending_reasons[:5],
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
