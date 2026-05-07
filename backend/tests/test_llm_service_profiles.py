import pytest

from app.config import settings
from app.services.llm_service import LLMService, use_request_model_name


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


@pytest.mark.asyncio
async def test_llm_service_routes_canary_traffic_to_active_model(monkeypatch):
    class FakeRedis:
        async def get(self, key):
            payloads = {
                "llm:active_model:tenant-z": (
                    '{"model_id":"model-canary","provider":"openai-compatible","base_url":"http://trained-llm:11434/v1",'
                    '"model":"tenant-z-sft","api_key":"secret","profile":"registry_active","canary_percent":20}'
                ),
                "llm:previous_active_model:tenant-z": (
                    '{"model_id":"model-prev","provider":"openai-compatible","base_url":"http://baseline-llm:11434/v1",'
                    '"model":"tenant-z-baseline","api_key":"secret-prev","profile":"registry_active"}'
                ),
            }
            return payloads.get(key)

    monkeypatch.setattr("app.services.llm_service.get_redis", lambda: FakeRedis())
    monkeypatch.setattr(
        "app.services.llm_service.in_canary_bucket",
        lambda key, *, percent, seed: key.startswith("tenant-z\n命中灰度"),
    )

    service = LLMService()
    target = await service._resolve_runtime_target_async("命中灰度", "这是一个新请求", "tenant-z")

    assert target["profile"] == "registry_canary_active"
    assert target["model"] == "tenant-z-sft"
    assert target["base_url"] == "http://trained-llm:11434/v1"
    assert target["rollout_canary_percent"] == 20


@pytest.mark.asyncio
async def test_llm_service_routes_non_canary_traffic_to_previous_model(monkeypatch):
    class FakeRedis:
        async def get(self, key):
            payloads = {
                "llm:active_model:tenant-z": (
                    '{"model_id":"model-canary","provider":"openai-compatible","base_url":"http://trained-llm:11434/v1",'
                    '"model":"tenant-z-sft","api_key":"secret","profile":"registry_active","canary_percent":20}'
                ),
                "llm:previous_active_model:tenant-z": (
                    '{"model_id":"model-prev","provider":"openai-compatible","base_url":"http://baseline-llm:11434/v1",'
                    '"model":"tenant-z-baseline","api_key":"secret-prev","profile":"registry_active"}'
                ),
            }
            return payloads.get(key)

    monkeypatch.setattr("app.services.llm_service.get_redis", lambda: FakeRedis())
    monkeypatch.setattr("app.services.llm_service.in_canary_bucket", lambda key, *, percent, seed: False)

    service = LLMService()
    target = await service._resolve_runtime_target_async("普通流量", "这是一个旧请求", "tenant-z")

    assert target["profile"] == "registry_previous_active"
    assert target["model"] == "tenant-z-baseline"
    assert target["base_url"] == "http://baseline-llm:11434/v1"
    assert target["api_key"] == "secret-prev"
    assert target["rollout_origin_model_id"] == "model-canary"
    assert target["rollout_canary_percent"] == 20


@pytest.mark.asyncio
async def test_llm_service_honors_user_selected_model(monkeypatch):
    class FakeRedis:
        async def get(self, key):
            payloads = {
                "llm:active_model:tenant-z": (
                    '{"provider":"openai-compatible","base_url":"http://trained-llm:11434/v1",'
                    '"model":"tenant-z-sft","api_key":"secret","profile":"registry_active"}'
                ),
            }
            return payloads.get(key)

    monkeypatch.setattr("app.services.llm_service.get_redis", lambda: FakeRedis())

    service = LLMService()
    with use_request_model_name("qwen2.5:7b"):
        target = await service._resolve_runtime_target_async("你是助手", "请总结当前制度", "tenant-z")

    assert target["profile"] == "user_selected_model"
    assert target["model"] == "qwen2.5:7b"
    assert target["base_url"] == service.base_url
    assert target["api_key"] == service.api_key
