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
            return {"safe": True, "reason": "", "severity": "low"}

        sidecar_result = await self.sidecar.check_input(user_input)
        if not sidecar_result.get("safe", True):
            return {
                "safe": False,
                "reason": sidecar_result.get("reason") or "Guardrails sidecar 拒绝该输入。",
                "severity": "high" if sidecar_result.get("mode") == "fail_closed" else "medium",
                "issues": sidecar_result.get("issues", []),
                "mode": sidecar_result.get("mode"),
            }

        lowered = user_input.lower()
        for phrase in self.DANGER_PHRASES:
            if phrase.lower() in lowered:
                return {"safe": False, "reason": "检测到疑似越权或提示注入请求，已拦截。", "severity": "medium"}

        return {"safe": True, "reason": "", "severity": "low", "mode": sidecar_result.get("mode")}
