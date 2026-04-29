"""Push notification registration and delivery service."""

from __future__ import annotations

import inspect
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psycopg2
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.push_device import PushDevice

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except ImportError:  # pragma: no cover
    GoogleAuthRequest = None
    service_account = None


class PushNotificationService:
    FCM_PLATFORMS = {"android", "web", "chrome", "capacitor-android"}
    APNS_PLATFORMS = {"ios", "iphone", "ipad", "capacitor-ios"}
    WECHAT_PLATFORMS = {"wechat", "weapp", "miniapp", "miniprogram"}
    FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
    DEFAULT_FCM_SERVICE_ACCOUNT_FILE = "/run/secrets/docmind/firebase-service-account.json"

    def __init__(self, db: AsyncSession | None = None, redis_client=None):
        self.db = db
        self.redis = redis_client
        self.logger = structlog.get_logger("docmind.push")

    async def register_device(
        self,
        *,
        tenant_id: str,
        user_id: str,
        platform: str,
        device_token: str,
        device_name: str | None,
        app_version: str | None,
    ) -> PushDevice:
        if self.db is None:
            raise RuntimeError("Async DB session is required for device registration.")
        result = await self.db.execute(
            select(PushDevice).where(
                PushDevice.tenant_id == tenant_id,
                PushDevice.user_id == user_id,
                PushDevice.device_token == device_token,
            )
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        normalized_platform = self._normalize_platform(platform)
        if existing is not None:
            existing.platform = normalized_platform
            existing.device_name = device_name
            existing.app_version = app_version
            existing.is_active = True
            existing.last_seen_at = now
            existing.updated_at = now
            return existing

        device = PushDevice(
            tenant_id=tenant_id,
            user_id=user_id,
            platform=normalized_platform,
            device_token=device_token,
            device_name=device_name,
            app_version=app_version,
            is_active=True,
            last_seen_at=now,
            updated_at=now,
        )
        self.db.add(device)
        await self.db.flush()
        return device

    async def unregister_device(self, *, tenant_id: str, user_id: str, device_token: str) -> bool:
        if self.db is None:
            raise RuntimeError("Async DB session is required for device unregistration.")
        result = await self.db.execute(
            select(PushDevice).where(
                PushDevice.tenant_id == tenant_id,
                PushDevice.user_id == user_id,
                PushDevice.device_token == device_token,
            )
        )
        device = result.scalar_one_or_none()
        if device is None:
            return False
        device.is_active = False
        device.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return True

    async def heartbeat_device(
        self,
        *,
        tenant_id: str,
        user_id: str,
        device_token: str,
        app_version: str | None = None,
    ) -> bool:
        if self.db is None:
            raise RuntimeError("Async DB session is required for device heartbeat.")
        result = await self.db.execute(
            select(PushDevice).where(
                PushDevice.tenant_id == tenant_id,
                PushDevice.user_id == user_id,
                PushDevice.device_token == device_token,
            )
        )
        device = result.scalar_one_or_none()
        if device is None:
            return False
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        device.is_active = True
        device.last_seen_at = now
        device.updated_at = now
        if app_version:
            device.app_version = app_version
        return True

    async def list_devices(self, *, tenant_id: str, user_id: str) -> list[PushDevice]:
        if self.db is None:
            raise RuntimeError("Async DB session is required for listing devices.")
        result = await self.db.execute(
            select(PushDevice)
            .where(PushDevice.tenant_id == tenant_id, PushDevice.user_id == user_id)
            .order_by(PushDevice.updated_at.desc())
        )
        return list(result.scalars().all())

    async def list_recent_events(self, *, tenant_id: str, user_id: str, limit: int = 20) -> list[dict]:
        if self.redis is None:
            return []
        key = f"push:events:{tenant_id}:{user_id}"
        rows = await self.redis.lrange(key, 0, max(limit - 1, 0))
        items: list[dict] = []
        for row in rows:
            try:
                items.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        return items

    async def send_test_notification(self, *, tenant_id: str, user_id: str, title: str, body: str) -> dict:
        if not settings.push_notifications_enabled:
            return {"sent": 0, "provider": "disabled", "title": title, "body": body}
        devices = await self.list_devices(tenant_id=tenant_id, user_id=user_id)
        payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": title,
            "body": body,
            "status": "test",
            "devices": [self._serialize_device(device) for device in devices if device.is_active],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        summary = await self._dispatch(payload)
        await self._record_notification({**payload, "delivery": summary})
        return {**summary, "title": title, "body": body}

    def send_document_status_sync(
        self,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str,
        title: str,
        status: str,
    ) -> dict:
        if not settings.push_notifications_enabled:
            return {"sent": 0, "provider": "disabled"}

        try:
            devices = self._load_active_devices_sync(tenant_id=tenant_id, user_id=user_id)
        except psycopg2.Error as exc:
            self.logger.warning(
                "push.load_devices_failed",
                tenant_id=tenant_id,
                user_id=user_id,
                document_id=document_id,
                error=str(exc),
            )
            return {"sent": 0, "provider": settings.push_notification_provider, "error": str(exc)}

        payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "document_id": document_id,
            "title": "文档处理状态更新",
            "body": f"文档《{title}》当前状态：{status}",
            "status": status,
            "devices": devices,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        summary = self._dispatch_sync(payload)
        self._record_notification_sync({**payload, "delivery": summary})
        return summary

    def _load_active_devices_sync(self, *, tenant_id: str, user_id: str) -> list[dict]:
        conn = psycopg2.connect(settings.postgres_dsn_sync)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT platform, device_token, device_name, app_version
                    FROM push_devices
                    WHERE tenant_id = %s AND user_id = %s AND is_active = TRUE
                    ORDER BY updated_at DESC
                    """,
                    (tenant_id, user_id),
                )
                rows = cur.fetchall()
                return [
                    {
                        "platform": self._normalize_platform(row[0]),
                        "device_token": row[1],
                        "device_name": row[2],
                        "app_version": row[3],
                    }
                    for row in rows
                ]
        finally:
            conn.close()

    async def _record_notification(self, payload: dict) -> None:
        if self.redis is None:
            return
        key = f"push:events:{payload['tenant_id']}:{payload['user_id']}"
        encoded = json.dumps(payload, ensure_ascii=False)
        await self.redis.lpush(key, encoded)
        await self.redis.ltrim(key, 0, 199)
        await self.redis.expire(key, 30 * 24 * 3600)

    def _record_notification_sync(self, payload: dict) -> None:
        if self.redis is None:
            return
        key = f"push:events:{payload['tenant_id']}:{payload['user_id']}"
        encoded = json.dumps(payload, ensure_ascii=False)
        operations = [
            self.redis.lpush(key, encoded),
            self.redis.ltrim(key, 0, 199),
            self.redis.expire(key, 30 * 24 * 3600),
        ]
        for op in operations:
            if inspect.isawaitable(op):
                import asyncio

                asyncio.run(op)

    async def _dispatch(self, payload: dict) -> dict:
        devices = payload.get("devices") or []
        results = await self._dispatch_multi_async(payload, devices)
        return self._summarize_delivery(results)

    def _dispatch_sync(self, payload: dict) -> dict:
        devices = payload.get("devices") or []
        results = self._dispatch_multi_sync(payload, devices)
        return self._summarize_delivery(results)

    async def _dispatch_multi_async(self, payload: dict, devices: list[dict]) -> list[dict]:
        mode = (settings.push_notification_provider or "log").lower()
        if mode in {"log", "webhook", "fcm", "apns", "wechat"}:
            return await self._dispatch_single_provider_async(mode, payload, devices)

        results: list[dict] = []
        grouped = self._group_devices_by_provider(devices)
        if grouped["fcm"]:
            results.extend(await self._dispatch_single_provider_async("fcm", payload, grouped["fcm"]))
        if grouped["apns"]:
            results.extend(await self._dispatch_single_provider_async("apns", payload, grouped["apns"]))
        if grouped["wechat"]:
            results.extend(await self._dispatch_single_provider_async("wechat", payload, grouped["wechat"]))
        if grouped["fallback"]:
            results.extend(await self._dispatch_single_provider_async("log", payload, grouped["fallback"]))
        return results

    def _dispatch_multi_sync(self, payload: dict, devices: list[dict]) -> list[dict]:
        mode = (settings.push_notification_provider or "log").lower()
        if mode in {"log", "webhook", "fcm", "apns", "wechat"}:
            return self._dispatch_single_provider_sync(mode, payload, devices)

        results: list[dict] = []
        grouped = self._group_devices_by_provider(devices)
        if grouped["fcm"]:
            results.extend(self._dispatch_single_provider_sync("fcm", payload, grouped["fcm"]))
        if grouped["apns"]:
            results.extend(self._dispatch_single_provider_sync("apns", payload, grouped["apns"]))
        if grouped["wechat"]:
            results.extend(self._dispatch_single_provider_sync("wechat", payload, grouped["wechat"]))
        if grouped["fallback"]:
            results.extend(self._dispatch_single_provider_sync("log", payload, grouped["fallback"]))
        return results

    async def _dispatch_single_provider_async(self, provider: str, payload: dict, devices: list[dict]) -> list[dict]:
        if not devices:
            return []
        if provider == "webhook":
            return [await self._send_webhook_async(payload, devices)]
        if provider == "fcm":
            return [await self._send_fcm_async(payload, devices)]
        if provider == "apns":
            return [await self._send_apns_async(payload, devices)]
        if provider == "wechat":
            return await self._send_wechat_async(payload, devices)
        return [self._send_log(payload, devices, provider="log")]

    def _dispatch_single_provider_sync(self, provider: str, payload: dict, devices: list[dict]) -> list[dict]:
        if not devices:
            return []
        if provider == "webhook":
            return [self._send_webhook_sync(payload, devices)]
        if provider == "fcm":
            return [self._send_fcm_sync(payload, devices)]
        if provider == "apns":
            return [self._send_apns_sync(payload, devices)]
        if provider == "wechat":
            return self._send_wechat_sync(payload, devices)
        return [self._send_log(payload, devices, provider="log")]

    async def _send_webhook_async(self, payload: dict, devices: list[dict]) -> dict:
        if not settings.push_notification_webhook_url:
            return self._provider_not_configured("webhook", payload, devices)
        try:
            timeout = httpx.Timeout(10.0, connect=2.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(settings.push_notification_webhook_url, json={**payload, "devices": devices})
                response.raise_for_status()
            return self._provider_success("webhook", devices)
        except httpx.HTTPError as exc:
            return self._provider_failure("webhook", devices, str(exc))

    def _send_webhook_sync(self, payload: dict, devices: list[dict]) -> dict:
        if not settings.push_notification_webhook_url:
            return self._provider_not_configured("webhook", payload, devices)
        try:
            with httpx.Client(timeout=10.0) as client:
                client.post(settings.push_notification_webhook_url, json={**payload, "devices": devices}).raise_for_status()
            return self._provider_success("webhook", devices)
        except httpx.HTTPError as exc:
            return self._provider_failure("webhook", devices, str(exc))

    async def _send_fcm_async(self, payload: dict, devices: list[dict]) -> dict:
        if not self._fcm_configured():
            return self._provider_not_configured("fcm", payload, devices)
        request_payload, headers, endpoint = self._build_fcm_request(payload, devices)
        try:
            timeout = httpx.Timeout(10.0, connect=2.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=request_payload, headers=headers)
                response.raise_for_status()
                self.logger.info("push.fcm_response", status_code=response.status_code, response=response.text[:500])
            return self._provider_success("fcm", devices)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000] if exc.response is not None else ""
            return self._provider_failure("fcm", devices, f"{exc}. body={body}")
        except httpx.HTTPError as exc:
            return self._provider_failure("fcm", devices, str(exc))

    def _send_fcm_sync(self, payload: dict, devices: list[dict]) -> dict:
        if not self._fcm_configured():
            return self._provider_not_configured("fcm", payload, devices)
        request_payload, headers, endpoint = self._build_fcm_request(payload, devices)
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(endpoint, json=request_payload, headers=headers)
                response.raise_for_status()
                self.logger.info("push.fcm_response", status_code=response.status_code, response=response.text[:500])
            return self._provider_success("fcm", devices)
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000] if exc.response is not None else ""
            return self._provider_failure("fcm", devices, f"{exc}. body={body}")
        except httpx.HTTPError as exc:
            return self._provider_failure("fcm", devices, str(exc))

    async def _send_apns_async(self, payload: dict, devices: list[dict]) -> dict:
        if not self._apns_configured():
            return self._provider_not_configured("apns", payload, devices)
        results: list[dict] = []
        timeout = httpx.Timeout(10.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout, http2=True) as client:
            for device in devices:
                try:
                    response = await client.post(
                        f"{settings.push_apns_endpoint.rstrip('/')}/3/device/{device['device_token']}",
                        json={
                            "aps": {
                                "alert": {"title": payload.get("title"), "body": payload.get("body")},
                                "sound": "default",
                            },
                            "meta": {"status": payload.get("status"), "document_id": payload.get("document_id")},
                        },
                        headers={
                            "authorization": f"bearer {settings.push_apns_auth_token}",
                            "apns-topic": settings.push_apns_topic,
                            "apns-priority": settings.push_apns_priority,
                        },
                    )
                    response.raise_for_status()
                    results.append(self._provider_success("apns", [device]))
                except httpx.HTTPError as exc:
                    results.append(self._provider_failure("apns", [device], str(exc)))
        return self._collapse_results("apns", results)

    def _send_apns_sync(self, payload: dict, devices: list[dict]) -> dict:
        if not self._apns_configured():
            return self._provider_not_configured("apns", payload, devices)
        results: list[dict] = []
        with httpx.Client(timeout=10.0, http2=True) as client:
            for device in devices:
                try:
                    response = client.post(
                        f"{settings.push_apns_endpoint.rstrip('/')}/3/device/{device['device_token']}",
                        json={
                            "aps": {
                                "alert": {"title": payload.get("title"), "body": payload.get("body")},
                                "sound": "default",
                            },
                            "meta": {"status": payload.get("status"), "document_id": payload.get("document_id")},
                        },
                        headers={
                            "authorization": f"bearer {settings.push_apns_auth_token}",
                            "apns-topic": settings.push_apns_topic,
                            "apns-priority": settings.push_apns_priority,
                        },
                    )
                    response.raise_for_status()
                    results.append(self._provider_success("apns", [device]))
                except httpx.HTTPError as exc:
                    results.append(self._provider_failure("apns", [device], str(exc)))
        return self._collapse_results("apns", results)

    async def _send_wechat_async(self, payload: dict, devices: list[dict]) -> list[dict]:
        if not self._wechat_configured():
            return [self._provider_not_configured("wechat", payload, devices)]
        timeout = httpx.Timeout(10.0, connect=2.0)
        results: list[dict] = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            for device in devices:
                try:
                    response = await client.post(
                        f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={settings.push_wechat_access_token}",
                        json={
                            "touser": device["device_token"],
                            "template_id": settings.push_wechat_template_id,
                            "page": settings.push_wechat_page,
                            "miniprogram_state": settings.push_wechat_miniprogram_state,
                            "lang": settings.push_wechat_lang,
                            "data": {
                                "thing1": {"value": str(payload.get("title") or "DocMind 通知")[:20]},
                                "thing2": {"value": str(payload.get("body") or "您有一条新消息")[:20]},
                            },
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    if body.get("errcode", 0) != 0:
                        results.append(self._provider_failure("wechat", [device], body.get("errmsg", "wechat error")))
                    else:
                        results.append(self._provider_success("wechat", [device]))
                except (httpx.HTTPError, ValueError) as exc:
                    results.append(self._provider_failure("wechat", [device], str(exc)))
        return results

    def _send_wechat_sync(self, payload: dict, devices: list[dict]) -> list[dict]:
        if not self._wechat_configured():
            return [self._provider_not_configured("wechat", payload, devices)]
        results: list[dict] = []
        with httpx.Client(timeout=10.0) as client:
            for device in devices:
                try:
                    response = client.post(
                        f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={settings.push_wechat_access_token}",
                        json={
                            "touser": device["device_token"],
                            "template_id": settings.push_wechat_template_id,
                            "page": settings.push_wechat_page,
                            "miniprogram_state": settings.push_wechat_miniprogram_state,
                            "lang": settings.push_wechat_lang,
                            "data": {
                                "thing1": {"value": str(payload.get("title") or "DocMind 通知")[:20]},
                                "thing2": {"value": str(payload.get("body") or "您有一条新消息")[:20]},
                            },
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    if body.get("errcode", 0) != 0:
                        results.append(self._provider_failure("wechat", [device], body.get("errmsg", "wechat error")))
                    else:
                        results.append(self._provider_success("wechat", [device]))
                except (httpx.HTTPError, ValueError) as exc:
                    results.append(self._provider_failure("wechat", [device], str(exc)))
        return results

    def _send_log(self, payload: dict, devices: list[dict], provider: str = "log") -> dict:
        self.logger.info(
            "push.dispatch_log",
            provider=provider,
            tenant_id=payload.get("tenant_id"),
            user_id=payload.get("user_id"),
            device_count=len(devices),
            payload={**payload, "devices": devices},
        )
        return self._provider_success(provider, devices)

    def _build_fcm_request(self, payload: dict, devices: list[dict]) -> tuple[dict[str, Any], dict[str, str], str]:
        tokens = [device["device_token"] for device in devices]
        service_account_file = self._resolve_fcm_service_account_file()
        project_id = self._resolve_fcm_project_id(service_account_file)
        if service_account_file:
            access_token = self._load_fcm_access_token_from_service_account()
            endpoint = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
            body = {
                "message": {
                    "token": tokens[0],
                    "notification": {"title": payload.get("title"), "body": payload.get("body")},
                    "data": {
                        "status": str(payload.get("status") or ""),
                        "document_id": str(payload.get("document_id") or ""),
                    },
                }
            }
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            return body, headers, endpoint

        endpoint = settings.push_fcm_endpoint
        if settings.push_fcm_access_token and settings.push_fcm_project_id:
            endpoint = f"https://fcm.googleapis.com/v1/projects/{settings.push_fcm_project_id}/messages:send"
            body = {
                "message": {
                    "token": tokens[0],
                    "notification": {"title": payload.get("title"), "body": payload.get("body")},
                    "data": {
                        "status": str(payload.get("status") or ""),
                        "document_id": str(payload.get("document_id") or ""),
                    },
                }
            }
            headers = {"Authorization": f"Bearer {settings.push_fcm_access_token}", "Content-Type": "application/json"}
            return body, headers, endpoint

        body = {
            "registration_ids": tokens,
            "notification": {"title": payload.get("title"), "body": payload.get("body")},
            "data": {"status": payload.get("status"), "document_id": payload.get("document_id")},
        }
        headers = {"Authorization": f"key={settings.push_fcm_server_key}", "Content-Type": "application/json"}
        return body, headers, endpoint

    def _load_fcm_access_token_from_service_account(self) -> str:
        path = Path(self._resolve_fcm_service_account_file())
        if not path.exists():
            raise RuntimeError(f"FCM service account file not found: {path}")
        if service_account is None or GoogleAuthRequest is None:
            raise RuntimeError("google-auth is not installed")
        credentials = service_account.Credentials.from_service_account_file(str(path), scopes=[self.FCM_SCOPE])
        credentials.refresh(GoogleAuthRequest())
        token = credentials.token
        if not token:
            raise RuntimeError("Unable to obtain Firebase access token from service account")
        return token

    def _group_devices_by_provider(self, devices: list[dict]) -> dict[str, list[dict]]:
        groups = {"fcm": [], "apns": [], "wechat": [], "fallback": []}
        for device in devices:
            platform = self._normalize_platform(device.get("platform"))
            if platform in self.FCM_PLATFORMS:
                groups["fcm"].append(device)
            elif platform in self.APNS_PLATFORMS:
                groups["apns"].append(device)
            elif platform in self.WECHAT_PLATFORMS:
                groups["wechat"].append(device)
            else:
                groups["fallback"].append(device)
        return groups

    def _summarize_delivery(self, results: list[dict]) -> dict:
        sent = sum(int(item.get("sent", 0)) for item in results)
        failed = sum(int(item.get("failed", 0)) for item in results)
        provider_counts = dict(Counter(item.get("provider", "unknown") for item in results))
        status = "ok" if failed == 0 else "partial_failed"
        return {
            "sent": sent,
            "failed": failed,
            "provider": settings.push_notification_provider,
            "status": status,
            "providers": provider_counts,
            "results": results,
        }

    def _collapse_results(self, provider: str, results: list[dict]) -> dict:
        if not results:
            return self._provider_success(provider, [])
        sent = sum(item.get("sent", 0) for item in results)
        failed = sum(item.get("failed", 0) for item in results)
        errors = [item.get("error") for item in results if item.get("error")]
        if failed and settings.push_notification_fail_closed:
            return self._provider_failure(provider, [], "; ".join(errors) or "delivery failed")
        return {
            "provider": provider,
            "sent": sent,
            "failed": failed,
            "error": "; ".join(errors) if errors else None,
            "device_count": sent + failed,
        }

    def _provider_success(self, provider: str, devices: list[dict]) -> dict:
        return {"provider": provider, "sent": len(devices), "failed": 0, "error": None, "device_count": len(devices)}

    def _provider_not_configured(self, provider: str, payload: dict, devices: list[dict]) -> dict:
        self.logger.warning(
            "push.provider_not_configured",
            provider=provider,
            device_count=len(devices),
        )
        if settings.push_notification_fail_closed:
            return self._provider_failure(provider, devices, "provider_not_configured")
        return self._send_log(payload, devices, provider=f"{provider}_fallback_log")

    def _provider_failure(self, provider: str, devices: list[dict], error: str) -> dict:
        self.logger.warning(
            "push.dispatch_failed",
            provider=provider,
            error=error,
            device_count=len(devices),
        )
        return {"provider": provider, "sent": 0, "failed": len(devices), "error": error, "device_count": len(devices)}

    def _fcm_configured(self) -> bool:
        return bool(
            settings.push_fcm_server_key
            or (settings.push_fcm_access_token and settings.push_fcm_project_id)
            or (self._resolve_fcm_service_account_file() and self._resolve_fcm_project_id(self._resolve_fcm_service_account_file()))
        )

    def _resolve_fcm_service_account_file(self) -> str:
        configured = (settings.push_fcm_service_account_file or "").strip()
        if configured:
            return configured
        default_path = Path(self.DEFAULT_FCM_SERVICE_ACCOUNT_FILE)
        return str(default_path) if default_path.exists() else ""

    def _resolve_fcm_project_id(self, service_account_file: str | None = None) -> str:
        if settings.push_fcm_project_id:
            return settings.push_fcm_project_id
        path_value = service_account_file or self._resolve_fcm_service_account_file()
        if not path_value:
            return ""
        path = Path(path_value)
        if not path.exists():
            return ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return str(payload.get("project_id") or "").strip()

    def _apns_configured(self) -> bool:
        return bool(settings.push_apns_topic and settings.push_apns_auth_token)

    def _wechat_configured(self) -> bool:
        return bool(settings.push_wechat_access_token and settings.push_wechat_template_id)

    def _normalize_platform(self, platform: str | None) -> str:
        return str(platform or "unknown").strip().lower()

    def _serialize_device(self, device: PushDevice) -> dict:
        return {
            "platform": self._normalize_platform(device.platform),
            "device_token": device.device_token,
            "device_name": device.device_name,
            "app_version": device.app_version,
        }
