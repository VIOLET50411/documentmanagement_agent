from __future__ import annotations

from app.config import settings
from app.services.security_policy_service import SecurityPolicyService


def test_security_policy_financial_profile_blocks_missing_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "security_policy_profile", "financial")
    monkeypatch.setattr(settings, "guardrails_enabled", True)
    monkeypatch.setattr(settings, "pii_masking_enabled", True)
    monkeypatch.setattr(settings, "pii_presidio_enabled", True)
    monkeypatch.setattr(settings, "watermark_enabled", True)
    monkeypatch.setattr(settings, "auth_allow_public_registration", False)
    monkeypatch.setattr(settings, "clamav_enabled", True)
    monkeypatch.setattr(settings, "clamav_fail_closed", False)
    monkeypatch.setattr(settings, "guardrails_sidecar_url", "http://guardrails")
    monkeypatch.setattr(settings, "guardrails_fail_closed", False)
    monkeypatch.setattr(settings, "auth_allowlist_domains", "swu.edu.cn")
    monkeypatch.setattr(settings, "auth_blocklist_domains", "blocked.example.com")
    monkeypatch.setattr(SecurityPolicyService, "_guardrails_sidecar_alive", lambda self: False)
    monkeypatch.setattr("app.services.security_policy_service.FileScanner.health", lambda self: {"available": True})

    payload = SecurityPolicyService().evaluate()

    assert payload["profile"] == "financial"
    assert payload["blocking"] is True
    assert payload["status"] == "blocked"
    assert payload["auto_action"] == "block_high_risk_operations"
    assert "guardrails_fail_closed" in payload["missing_control_ids"]
    assert "guardrails_sidecar_alive" in payload["missing_control_ids"]
    assert payload["control_counts"]["critical"] >= 2
    assert any(item["id"] == "guardrails_fail_closed" for item in payload["failed_controls"])
    assert any("Guardrails" in action for action in payload["recommended_actions"])


def test_security_policy_enterprise_profile_warns_without_blocking(monkeypatch):
    monkeypatch.setattr(settings, "security_policy_profile", "enterprise")
    monkeypatch.setattr(settings, "guardrails_enabled", True)
    monkeypatch.setattr(settings, "pii_masking_enabled", True)
    monkeypatch.setattr(settings, "pii_presidio_enabled", False)
    monkeypatch.setattr(settings, "watermark_enabled", True)
    monkeypatch.setattr(settings, "auth_allow_public_registration", False)
    monkeypatch.setattr(SecurityPolicyService, "_guardrails_sidecar_alive", lambda self: False)
    monkeypatch.setattr("app.services.security_policy_service.FileScanner.health", lambda self: {"available": True})

    payload = SecurityPolicyService().evaluate()

    assert payload["profile"] == "enterprise"
    assert payload["compliant"] is False
    assert payload["blocking"] is False
    assert payload["status"] == "warning"
    assert payload["auto_action"] == "monitor_and_warn"
    assert "pii_presidio_enabled" in payload["missing_control_ids"]
