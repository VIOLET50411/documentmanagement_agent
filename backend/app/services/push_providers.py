"""Push notification provider base class and strategy dispatch."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog


class BasePushProvider(ABC):
    """Base class for push notification providers (Strategy pattern)."""

    logger = structlog.get_logger("docmind.push")

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def supported_platforms(self) -> set[str]:
        ...

    @abstractmethod
    async def send_async(self, payload: dict, devices: list[dict]) -> dict:
        ...

    @abstractmethod
    def send_sync(self, payload: dict, devices: list[dict]) -> dict:
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        ...

    def health(self) -> dict:
        return {
            "provider": self.provider_name,
            "configured": self.is_configured(),
            "ready": self.is_configured(),
            "supported_platforms": sorted(self.supported_platforms),
        }

    def _provider_success(self, devices: list[dict]) -> dict:
        return {
            "provider": self.provider_name,
            "sent": len(devices),
            "success": True,
            "devices": [d.get("device_token", "")[-8:] for d in devices],
        }

    def _provider_failure(self, devices: list[dict], error: str) -> dict:
        return {
            "provider": self.provider_name,
            "sent": 0,
            "success": False,
            "error": error,
            "devices": [d.get("device_token", "")[-8:] for d in devices],
        }

    def _provider_not_configured(self) -> dict:
        return {
            "provider": self.provider_name,
            "sent": 0,
            "success": False,
            "error": f"{self.provider_name} provider not configured",
        }


class LogProvider(BasePushProvider):
    """Default provider: logs notification payloads."""

    @property
    def provider_name(self) -> str:
        return "log"

    @property
    def supported_platforms(self) -> set[str]:
        return {"*"}

    def is_configured(self) -> bool:
        return True

    async def send_async(self, payload: dict, devices: list[dict]) -> dict:
        self.logger.info("push.log_dispatch", payload=payload, device_count=len(devices))
        return self._provider_success(devices)

    def send_sync(self, payload: dict, devices: list[dict]) -> dict:
        self.logger.info("push.log_dispatch", payload=payload, device_count=len(devices))
        return self._provider_success(devices)


class WebhookProvider(BasePushProvider):
    """Webhook-based push notification provider."""

    @property
    def provider_name(self) -> str:
        return "webhook"

    @property
    def supported_platforms(self) -> set[str]:
        return {"*"}

    def is_configured(self) -> bool:
        from app.config import settings
        return bool(settings.push_notification_webhook_url)

    async def send_async(self, payload: dict, devices: list[dict]) -> dict:
        import httpx
        from app.config import settings
        if not self.is_configured():
            return self._provider_not_configured()
        try:
            timeout = httpx.Timeout(10.0, connect=2.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(settings.push_notification_webhook_url, json={**payload, "devices": devices})
                resp.raise_for_status()
            return self._provider_success(devices)
        except Exception as exc:
            return self._provider_failure(devices, str(exc))

    def send_sync(self, payload: dict, devices: list[dict]) -> dict:
        import httpx
        from app.config import settings
        if not self.is_configured():
            return self._provider_not_configured()
        try:
            with httpx.Client(timeout=10.0) as client:
                client.post(settings.push_notification_webhook_url, json={**payload, "devices": devices}).raise_for_status()
            return self._provider_success(devices)
        except Exception as exc:
            return self._provider_failure(devices, str(exc))


def get_provider(name: str) -> BasePushProvider:
    """Factory method to get a provider by name."""
    providers = {
        "log": LogProvider,
        "webhook": WebhookProvider,
    }
    cls = providers.get(name.lower(), LogProvider)
    return cls()
