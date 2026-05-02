"""Input guard with local heuristic checks."""

from __future__ import annotations

from app.config import settings
from app.services.guardrails_service import GuardrailsService


class InputGuard:
    """Block jailbreak, prompt injection, and malicious queries."""

    DANGER_PHRASES = (
        "请忽略之前的指令",
        "忽略以上规则",
        "ignore previous",
        "ignore all instructions",
        "forget your instructions",
        "system prompt",
        "developer message",
        "reveal the prompt",
        "输出系统提示词",
        "绕过安全限制",
    )

    def __init__(self):
        self.enabled = settings.guardrails_enabled
        self.sidecar = GuardrailsService()

    async def check(self, user_input: str) -> dict:
        if not self.enabled or not user_input:
            return self._build_result(
                safe=True,
                reason="",
                severity="low",
                issues=[],
                mode="disabled" if not self.enabled else "empty",
                decision_source="disabled" if not self.enabled else "input_validation",
                degraded=False,
            )

        sidecar_result = await self.sidecar.check_input(user_input)
        if not sidecar_result.get("safe", True):
            mode = sidecar_result.get("mode") or "sidecar"
            return self._build_result(
                safe=False,
                reason=sidecar_result.get("reason") or "Guardrails sidecar 拒绝该输入。",
                severity="high" if mode == "fail_closed" else "medium",
                issues=sidecar_result.get("issues", []),
                mode=mode,
                decision_source="guardrails_sidecar",
                degraded=mode in {"degraded", "fail_closed"},
            )

        lowered = user_input.lower()
        for phrase in self.DANGER_PHRASES:
            if phrase.lower() in lowered:
                return self._build_result(
                    safe=False,
                    reason="检测到疑似越权或提示注入请求，已拦截。",
                    severity="medium",
                    issues=["prompt_injection_phrase"],
                    mode="local_rule",
                    decision_source="local_heuristic",
                    degraded=False,
                )

        mode = sidecar_result.get("mode") or "sidecar"
        return self._build_result(
            safe=True,
            reason=sidecar_result.get("reason", ""),
            severity="low",
            issues=sidecar_result.get("issues", []),
            mode=mode,
            decision_source="guardrails_sidecar" if mode in {"sidecar", "degraded", "fail_closed"} else "local_heuristic",
            degraded=mode == "degraded",
        )

    def _build_result(
        self,
        *,
        safe: bool,
        reason: str,
        severity: str,
        issues: list[str],
        mode: str,
        decision_source: str,
        degraded: bool,
    ) -> dict:
        return {
            "safe": safe,
            "blocked": not safe,
            "reason": reason,
            "severity": severity,
            "issues": issues,
            "mode": mode,
            "decision_source": decision_source,
            "degraded": degraded,
        }
