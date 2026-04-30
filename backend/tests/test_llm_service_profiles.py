import pytest

from app.config import settings
from app.services.llm_service import LLMService


def test_llm_service_uses_enterprise_profile_for_keyword_hit(monkeypatch):
    monkeypatch.setattr(settings, "llm_enterprise_enabled", True)
    monkeypatch.setattr(settings, "llm_enterprise_model_name", "qwen-enterprise:7b")
    monkeypatch.setattr(settings, "llm_enterprise_api_base_url", "http://enterprise-llm:11434/v1")
    monkeypatch.setattr(settings, "llm_enterprise_api_key", "enterprise-key")
    monkeypatch.setattr(settings, "llm_enterprise_keywords", "制度,审批,合规")
    monkeypatch.setattr(settings, "llm_enterprise_force_tenants", "")
    monkeypatch.setattr(settings, "llm_enterprise_canary_percent", 0)

    service = LLMService()
    target = service._resolve_runtime_target("你是企业制度助手", "请总结当前审批制度要求", "tenant-a")

    assert target["profile"] == "enterprise"
    assert target["model"] == "qwen-enterprise:7b"
    assert target["base_url"] == "http://enterprise-llm:11434/v1"
    assert target["api_key"] == "enterprise-key"


def test_llm_service_keeps_default_profile_without_match(monkeypatch):
    monkeypatch.setattr(settings, "llm_enterprise_enabled", True)
    monkeypatch.setattr(settings, "llm_enterprise_model_name", "qwen-enterprise:7b")
    monkeypatch.setattr(settings, "llm_enterprise_api_base_url", "http://enterprise-llm:11434/v1")
    monkeypatch.setattr(settings, "llm_enterprise_api_key", "")
    monkeypatch.setattr(settings, "llm_enterprise_keywords", "制度,审批,合规")
    monkeypatch.setattr(settings, "llm_enterprise_force_tenants", "")
    monkeypatch.setattr(settings, "llm_enterprise_canary_percent", 0)

    service = LLMService()
    target = service._resolve_runtime_target("你是通用助手", "请讲一个笑话", "tenant-b")

    assert target["profile"] == "default"
    assert target["model"] == service.model
    assert target["base_url"] == service.base_url


@pytest.mark.asyncio
async def test_llm_service_uses_active_registry_override(monkeypatch):
    class FakeRedis:
        async def get(self, key):
            assert key == "llm:active_model:tenant-z"
            return (
                '{"provider":"openai-compatible","base_url":"http://trained-llm:11434/v1",'
                '"model":"tenant-z-sft","api_key":"secret","profile":"registry_active"}'
            )

    monkeypatch.setattr("app.services.llm_service.get_redis", lambda: FakeRedis())

    service = LLMService()
    target = await service._resolve_runtime_target_async("你是助手", "随便聊聊", "tenant-z")

    assert target["profile"] == "registry_active"
    assert target["model"] == "tenant-z-sft"
    assert target["base_url"] == "http://trained-llm:11434/v1"
    assert target["api_key"] == "secret"
