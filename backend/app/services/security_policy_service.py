"""Security policy profile evaluation."""

from __future__ import annotations

import httpx

from app.config import settings
from app.security.file_scanner import FileScanner


class SecurityPolicyService:
    """Evaluate enterprise/financial policy controls."""

    def evaluate(self) -> dict:
        profile = (settings.security_policy_profile or "enterprise").strip().lower()
        if profile not in {"enterprise", "financial"}:
            profile = "enterprise"

        guardrails_alive = self._guardrails_sidecar_alive()
        controls = [
            self._control(
                "guardrails_enabled",
                bool(settings.guardrails_enabled),
                "Guardrails 总开关已启用",
                severity="critical" if profile == "financial" else "high",
                category="guardrails",
            ),
            self._control(
                "pii_masking_enabled",
                bool(settings.pii_masking_enabled),
                "PII 脱敏已启用",
                severity="high",
                category="pii",
            ),
            self._control(
                "pii_presidio_enabled",
                bool(settings.pii_presidio_enabled),
                "Presidio PII 识别已启用",
                severity="high" if profile == "financial" else "medium",
                category="pii",
            ),
            self._control(
                "watermark_enabled",
                bool(settings.watermark_enabled),
                "输出水印已启用",
                severity="medium",
                category="forensics",
            ),
            self._control(
                "public_registration_closed",
                not bool(settings.auth_allow_public_registration),
                "公共注册入口已关闭",
                severity="medium",
                category="identity",
            ),
            self._control(
                "runtime_v2_only",
                True,
                "运行时仅保留 v2",
                severity="medium",
                category="runtime",
            ),
        ]
        if profile == "financial":
            controls.extend(
                [
                    self._control(
                        "clamav_enabled",
                        bool(settings.clamav_enabled),
                        "ClamAV 已启用",
                        severity="critical",
                        category="malware",
                    ),
                    self._control(
                        "clamav_fail_closed",
                        bool(settings.clamav_fail_closed),
                        "ClamAV 已开启 fail-closed",
                        severity="critical",
                        category="malware",
                    ),
                    self._control(
                        "guardrails_sidecar_url",
                        bool(settings.guardrails_sidecar_url),
                        "Guardrails sidecar 地址已配置",
                        severity="critical",
                        category="guardrails",
                    ),
                    self._control(
                        "guardrails_sidecar_alive",
                        guardrails_alive,
                        "Guardrails sidecar 可达",
                        severity="critical",
                        category="guardrails",
                    ),
                    self._control(
                        "guardrails_fail_closed",
                        bool(settings.guardrails_fail_closed),
                        "Guardrails 已开启 fail-closed",
                        severity="critical",
                        category="guardrails",
                    ),
                    self._control(
                        "mail_allowlist_configured",
                        bool(settings.auth_allowlist_domain_list),
                        "邮件白名单已配置",
                        severity="high",
                        category="identity",
                    ),
                    self._control(
                        "mail_blocklist_configured",
                        bool(settings.auth_blocklist_domain_list),
                        "邮件黑名单已配置",
                        severity="medium",
                        category="identity",
                    ),
                ]
            )

        failed = [{"id": item["id"], "message": item["message"]} for item in controls if not item["ok"]]
        blocking_controls = [item for item in controls if (not item["ok"]) and item["severity"] in {"critical", "high"}]
        warning_controls = [item for item in controls if (not item["ok"]) and item["severity"] not in {"critical", "high"}]
        control_counts = self._count_by_severity(controls)
        recommended_actions = self._recommended_actions(blocking_controls, warning_controls)
        blocking = len(blocking_controls) > 0
        compliant = len(failed) == 0
        enforcement_level = "financial_fail_closed" if profile == "financial" else "enterprise_guarded"
        auto_action = "block_high_risk_operations" if blocking else ("monitor_and_warn" if not compliant else "allow")
        scanner_health = FileScanner().health()
        return {
            "profile": profile,
            "enforcement_level": enforcement_level,
            "compliant": compliant,
            "blocking": blocking,
            "status": "blocked" if blocking else ("warning" if not compliant else "compliant"),
            "auto_action": auto_action,
            "failed_controls": failed,
            "blocking_controls": blocking_controls,
            "warning_controls": warning_controls,
            "required_control_ids": [item["id"] for item in controls],
            "missing_control_ids": [item["id"] for item in controls if not item["ok"]],
            "control_counts": control_counts,
            "recommended_actions": recommended_actions,
            "controls": controls,
            "clamav_health": scanner_health,
            "guardrails_sidecar": {
                "configured": bool(settings.guardrails_sidecar_url),
                "fail_closed": bool(settings.guardrails_fail_closed),
                "alive": guardrails_alive,
            },
            "pii": {
                "masking_enabled": bool(settings.pii_masking_enabled),
                "presidio_enabled": bool(settings.pii_presidio_enabled),
            },
        }

    def _control(
        self,
        control_id: str,
        ok: bool,
        message: str,
        *,
        severity: str,
        category: str,
    ) -> dict:
        return {
            "id": control_id,
            "ok": ok,
            "message": message,
            "severity": severity,
            "category": category,
            "blocking": (not ok) and severity in {"critical", "high"},
        }

    def _count_by_severity(self, controls: list[dict]) -> dict:
        counts = {"ok": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}
        for item in controls:
            if item["ok"]:
                counts["ok"] += 1
                continue
            severity = str(item.get("severity") or "low").lower()
            counts[severity] = counts.get(severity, 0) + 1
        return counts

    def _recommended_actions(self, blocking_controls: list[dict], warning_controls: list[dict]) -> list[str]:
        actions: list[str] = []
        for item in blocking_controls + warning_controls:
            control_id = str(item.get("id") or "")
            if control_id == "guardrails_sidecar_alive":
                actions.append("恢复 Guardrails sidecar 健康状态，避免输入输出检查降级。")
            elif control_id == "guardrails_fail_closed":
                actions.append("开启 Guardrails fail-closed，避免 sidecar 不可用时继续放行。")
            elif control_id == "clamav_enabled":
                actions.append("启用 ClamAV 恶意文件扫描。")
            elif control_id == "clamav_fail_closed":
                actions.append("为文件扫描启用 fail-closed 策略。")
            elif control_id == "pii_presidio_enabled":
                actions.append("启用 Presidio 或等效模型化 PII 检测。")
            elif control_id == "mail_allowlist_configured":
                actions.append("配置租户邮箱白名单，限制高风险账号接入。")
            elif control_id == "mail_blocklist_configured":
                actions.append("配置邮箱黑名单，补齐身份安全策略。")
            elif control_id == "guardrails_sidecar_url":
                actions.append("配置 Guardrails sidecar 地址并接入健康检查。")
            elif control_id == "guardrails_enabled":
                actions.append("启用 Guardrails 总开关。")
            elif control_id == "pii_masking_enabled":
                actions.append("启用 PII 脱敏，避免敏感信息明文输出。")
            elif control_id == "watermark_enabled":
                actions.append("启用输出水印，补齐审计与取证能力。")
        deduped: list[str] = []
        for action in actions:
            if action not in deduped:
                deduped.append(action)
        return deduped

    def _guardrails_sidecar_alive(self) -> bool:
        base = (settings.guardrails_sidecar_url or "").rstrip("/")
        if not base:
            return False
        try:
            with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0)) as client:
                resp = client.get(base + "/health")
                resp.raise_for_status()
            return True
        except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError):
            return False
