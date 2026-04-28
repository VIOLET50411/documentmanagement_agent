import pytest

from app.config import settings
from app.services.auth_service import AuthService


def test_auth_domain_policy_blocks_disposable_domain():
    original_allowlist = settings.auth_allowlist_domains
    original_blocklist = settings.auth_blocklist_domains
    try:
        settings.auth_allowlist_domains = "example.com,corp.local"
        settings.auth_blocklist_domains = "mailinator.com,temp-mail.org"
        service = AuthService(db=None)
        with pytest.raises(ValueError):
            service._validate_email_domain("test@mailinator.com")
    finally:
        settings.auth_allowlist_domains = original_allowlist
        settings.auth_blocklist_domains = original_blocklist
