"""Post-generation safety scanning."""

from __future__ import annotations

import re

from app.services.guardrails_service import GuardrailsService


class OutputGuard:
    """Scan output for PII leaks and policy violations."""

    PHONE_RE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
    ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
    BANK_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
    EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    ISSUE_LABELS = {
        "phone": "Possible phone number in output",
        "id_card": "Possible ID card number in output",
        "bank_card": "Possible bank card number in output",
        "email": "Possible email address in output",
        "guardrails_sidecar_unavailable": "Guardrails sidecar unavailable",
    }

    def __init__(self):
        self.sidecar = GuardrailsService()

    async def check(self, output: str, context: dict | None = None) -> dict:
        issues: list[str] = []
        if not output:
            return self._build_result(
                safe=True,
                issues=issues,
                reason="",
                severity="low",
                mode="empty",
                decision_source="output_validation",
                degraded=False,
            )

        sidecar_result = await self.sidecar.check_output(output)
        if not sidecar_result.get("safe", True):
            mode = sidecar_result.get("mode") or "sidecar"
            return self._build_result(
                safe=False,
                issues=self._normalize_issues(sidecar_result.get("issues", [])),
                reason=sidecar_result.get("reason", ""),
                severity="high" if mode == "fail_closed" else "medium",
                mode=mode,
                decision_source="guardrails_sidecar",
                degraded=mode in {"degraded", "fail_closed"},
            )

        if self._is_garbled(output):
            return self._build_result(
                safe=False,
                issues=["garbled_output"],
                reason="模型输出异常，已自动切换到规则化降级回答。请重新提问或继续细化问题。",
                severity="medium",
                mode="garbled_detection",
                decision_source="local_heuristic",
                degraded=True,
            )

        if self.PHONE_RE.search(output):
            issues.append("Possible phone number in output")
        if self.ID_RE.search(output):
            issues.append("Possible ID card number in output")
        if self.BANK_RE.search(output):
            issues.append("Possible bank card number in output")
        if self.EMAIL_RE.search(output):
            issues.append("Possible email address in output")

        return self._build_result(
            safe=len(issues) == 0,
            issues=issues,
            reason="" if not issues else "输出内容命中本地敏感信息规则。",
            severity="low" if not issues else "high",
            mode=sidecar_result.get("mode") or ("local_rule" if issues else "sidecar"),
            decision_source="local_heuristic" if issues else "guardrails_sidecar",
            degraded=sidecar_result.get("mode") == "degraded",
        )

    def _normalize_issues(self, issues: list[str]) -> list[str]:
        normalized: list[str] = []
        for issue in issues:
            normalized.append(self.ISSUE_LABELS.get(issue, issue))
        return normalized

    def _build_result(
        self,
        *,
        safe: bool,
        issues: list[str],
        reason: str,
        severity: str,
        mode: str,
        decision_source: str,
        degraded: bool,
    ) -> dict:
        return {
            "safe": safe,
            "blocked": not safe,
            "issues": issues,
            "reason": reason,
            "severity": severity,
            "mode": mode,
            "decision_source": decision_source,
            "degraded": degraded,
        }

    def _is_garbled(self, text: str) -> bool:
        """Detect garbled/garbage LLM output using multiple heuristics."""
        if not text or len(text.strip()) < 30:
            return False

        cleaned = text.replace(" ", "").replace("\n", "").replace("\r", "")
        total = len(cleaned)
        if total == 0:
            return False

        chinese_chars = sum(1 for c in cleaned if "\u4e00" <= c <= "\u9fff")
        latin_chars = sum(1 for c in cleaned if ("a" <= c <= "z") or ("A" <= c <= "Z"))

        chinese_ratio = chinese_chars / total
        latin_ratio = latin_chars / total

        if total < 100 and chinese_ratio > 0.3:
            return False

        if chinese_ratio < 0.10 and latin_ratio > 0.30:
            return True

        script_flags = set()
        for c in cleaned[:500]:
            cp = ord(c)
            if 0x0400 <= cp <= 0x04FF:
                script_flags.add("cyrillic")
            elif 0x0E00 <= cp <= 0x0E7F:
                script_flags.add("thai")
            elif 0x0600 <= cp <= 0x06FF:
                script_flags.add("arabic")
            elif 0x0370 <= cp <= 0x03FF:
                script_flags.add("greek")
            elif 0x1000 <= cp <= 0x109F:
                script_flags.add("myanmar")
        if len(script_flags) >= 2:
            return True

        code_markers = ["()", "{}", "[];", ");", "=>", "</>", "def ", "class ", "import ", "async ", "await ", "console.", "self."]
        if sum(1 for marker in code_markers if marker in text) >= 4:
            return True

        words = text.split()
        if len(words) > 50:
            avg_len = sum(len(w) for w in words) / len(words)
            if avg_len < 3.5 and latin_ratio > 0.20:
                return True

        return False
