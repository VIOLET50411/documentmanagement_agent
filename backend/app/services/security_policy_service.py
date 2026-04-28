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

        base_controls = [
            ("guardrails_enabled", bool(settings.guardrails_enabled), "Guardrails enabled"),
            ("pii_masking_enabled", bool(settings.pii_masking_enabled), "PII masking enabled"),
            ("pii_presidio_enabled", bool(settings.pii_presidio_enabled), "Presidio-backed PII recognition enabled"),
            ("watermark_enabled", bool(settings.watermark_enabled), "Watermark enabled"),
            ("public_registration_closed", not bool(settings.auth_allow_public_registration), "Public registration closed"),
            ("runtime_v2_only", True, "Runtime is v2 only"),
        ]
        financial_controls = [
            ("clamav_enabled", bool(settings.clamav_enabled), "ClamAV enabled"),
            ("clamav_fail_closed", bool(settings.clamav_fail_closed), "ClamAV fail-closed"),
            ("guardrails_sidecar_url", bool(settings.guardrails_sidecar_url), "Guardrails sidecar URL configured"),
            ("guardrails_sidecar_alive", self._guardrails_sidecar_alive(), "Guardrails sidecar reachable"),
            ("guardrails_fail_closed", bool(settings.guardrails_fail_closed), "Guardrails fail-closed"),
            ("mail_allowlist_configured", bool(settings.auth_allowlist_domain_list), "Allowlist email domains configured"),
            ("mail_blocklist_configured", bool(settings.auth_blocklist_domain_list), "Blocklist email domains configured"),
        ]

        controls = base_controls + (financial_controls if profile == "financial" else [])
        failed = [
            {"id": control_id, "message": message}
            for control_id, ok, message in controls
            if not ok
        ]
        scanner_health = FileScanner().health()
        return {
            "profile": profile,
            "compliant": len(failed) == 0,
            "failed_controls": failed,
            "controls": [
                {"id": control_id, "ok": ok, "message": message}
                for control_id, ok, message in controls
            ],
            "clamav_health": scanner_health,
            "guardrails_sidecar": {
                "configured": bool(settings.guardrails_sidecar_url),
                "fail_closed": bool(settings.guardrails_fail_closed),
                "alive": self._guardrails_sidecar_alive(),
            },
            "pii": {
                "masking_enabled": bool(settings.pii_masking_enabled),
                "presidio_enabled": bool(settings.pii_presidio_enabled),
            },
        }

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
