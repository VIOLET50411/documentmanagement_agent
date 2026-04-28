from app.config import settings
from app.services.platform_readiness_service import PlatformReadinessService


def test_registration_policy_when_public_registration_disabled():
    service = PlatformReadinessService(db=None, redis_client=None)
    original = settings.auth_allow_public_registration
    try:
        settings.auth_allow_public_registration = False
        assert service._check_registration_policy() is True
    finally:
        settings.auth_allow_public_registration = original


def test_registration_policy_when_public_registration_enabled_requires_lists():
    service = PlatformReadinessService(db=None, redis_client=None)
    original_public = settings.auth_allow_public_registration
    original_allow = settings.auth_allowlist_domains
    original_block = settings.auth_blocklist_domains
    try:
        settings.auth_allow_public_registration = True
        settings.auth_allowlist_domains = ""
        settings.auth_blocklist_domains = ""
        assert service._check_registration_policy() is False
        settings.auth_allowlist_domains = "example.com"
        settings.auth_blocklist_domains = "mailinator.com"
        assert service._check_registration_policy() is True
    finally:
        settings.auth_allow_public_registration = original_public
        settings.auth_allowlist_domains = original_allow
        settings.auth_blocklist_domains = original_block
