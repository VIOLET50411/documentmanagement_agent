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
from sqlalchemy import and_
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
    WECHAT_PLATFORMS = {"wechat", "weapp", "miniapp", "miniprogram"}
    FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
    DEFAULT_FCM_SERVICE_ACCOUNT_FILE = "/run/secrets/docmind/firebase-service-account.json"
    INVALID_FCM_CODES = {"invalidregistration", "notregistered", "unregistered", "invalid_argument"}
    INVALID_WECHAT_CODES = {40003, 40037, 43101}
    WECHAT_TOKEN_REFRESH_CODES = {40001, 42001}
    WECHAT_TOKEN_CACHE_KEY_PREFIX = "push:wechat:access_token:"

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

    async def summarize_devices(self, *, tenant_id: str, user_id: str, current_token: str | None = None) -> dict:
        devices = await self.list_devices(tenant_id=tenant_id, user_id=user_id)
        normalized_current = str(current_token or "").strip()
        matched_device = next((device for device in devices if device.device_token == normalized_current), None) if normalized_current else None

        by_platform: dict[str, dict[str, int]] = {}
        active_count = 0
        inactive_count = 0
        for device in devices:
            platform = self._normalize_platform(device.platform)
            bucket = by_platform.setdefault(platform, {"active": 0, "inactive": 0, "total": 0})
            bucket["total"] += 1
            if device.is_active:
                bucket["active"] += 1
                active_count += 1
            else:
                bucket["inactive"] += 1
                inactive_count += 1

        return {
            "total": len(devices),
            "active": active_count,
            "inactive": inactive_count,
            "by_platform": by_platform,
            "current_token_provided": bool(normalized_current),
            "current_token_status": (
                "matched_active"
                if matched_device and matched_device.is_active
                else "matched_inactive"
                if matched_device
                else "not_found"
                if normalized_current
                else "not_provided"
            ),
            "current_device": self._serialize_device_record(matched_device) if matched_device is not None else None,
        }

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

    async def resolve_wechat_openid(self, js_code: str) -> str:
        normalized_code = str(js_code or "").strip()
        if not normalized_code:
            raise ValueError("缺少微信登录 code")
        if self._resolve_wechat_auth_mode() != "app_secret":
            raise ValueError("微信小程序 appid/appsecret 未配置，无法换取 openid")

        timeout = httpx.Timeout(10.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session",
                params={
                    "appid": settings.push_wechat_app_id,
                    "secret": settings.push_wechat_app_secret,
                    "js_code": normalized_code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            body = response.json()

        openid = str(body.get("openid") or "").strip()
        if openid:
            return openid

        errmsg = str(body.get("errmsg") or "openid missing").strip()
        errcode = body.get("errcode")
        if errcode is not None:
            raise ValueError(f"微信 code2session 失败: {errcode} {errmsg}".strip())
        raise ValueError(f"微信 code2session 失败: {errmsg}".strip())

    async def get_health_summary(self, *, tenant_id: str) -> dict:
        provider = (settings.push_notification_provider or "log").lower()
        fcm_service_account_file = self._resolve_fcm_service_account_file()
        wechat_auth_mode = self._resolve_wechat_auth_mode()
        providers = {
            "log": {"configured": True, "ready": True},
            "webhook": {
                "configured": bool(settings.push_notification_webhook_url),
                "ready": bool(settings.push_notification_webhook_url),
                "webhook_url_configured": bool(settings.push_notification_webhook_url),
                "required_env_vars": ["PUSH_NOTIFICATION_WEBHOOK_URL"],
                "missing_env_vars": [] if settings.push_notification_webhook_url else ["PUSH_NOTIFICATION_WEBHOOK_URL"],
            },
            "fcm": {
                "implemented": True,
                "configured": self._fcm_configured(),
                "ready": self._fcm_configured(),
                "code_ready": True,
                "transport": "https",
                "delivery_mode": "v1" if self._uses_fcm_v1() else "legacy" if settings.push_fcm_server_key else "unconfigured",
                "supports_platforms": sorted(self.FCM_PLATFORMS),
                "mode": "v1" if self._uses_fcm_v1() else "legacy" if settings.push_fcm_server_key else "unconfigured",
                "service_account_file_configured": bool(fcm_service_account_file),
                "project_id": self._resolve_fcm_project_id(fcm_service_account_file) or settings.push_fcm_project_id or None,
                "required_env_vars": self._required_push_env_vars("fcm"),
                "missing_env_vars": self._missing_push_env_vars("fcm", fcm_service_account_file),
            },
            "wechat": {
                "implemented": True,
                "configured": self._wechat_configured(),
                "ready": self._wechat_configured(),
                "code_ready": True,
                "transport": "https",
                "delivery_mode": "subscribe_message",
                "supports_platforms": sorted(self.WECHAT_PLATFORMS),
                "endpoint": "https://api.weixin.qq.com/cgi-bin/message/subscribe/send",
                "template_id_configured": bool(settings.push_wechat_template_id),
                "access_token_configured": wechat_auth_mode in {"access_token", "app_secret"},
                "auth_mode": wechat_auth_mode,
                "app_id_configured": bool(settings.push_wechat_app_id),
                "app_secret_configured": bool(settings.push_wechat_app_secret),
                "required_env_vars": self._required_push_env_vars("wechat"),
                "missing_env_vars": self._missing_push_env_vars("wechat"),
            },
        }
        for provider_name, meta in providers.items():
            meta["next_step"] = self._build_provider_next_step(provider_name, meta)
        active_provider_keys = [name for name, meta in providers.items() if name != "log" and meta.get("configured")]
        active_provider_readiness = {
            name: {
                "configured": bool(meta.get("configured")),
                "ready": bool(meta.get("ready")),
            }
            for name, meta in providers.items()
            if name != "log"
        }
        issues: list[str] = []
        selected_ready = True
        if settings.push_notifications_enabled:
            if provider == "multi":
                selected_ready = bool(active_provider_keys)
                if not active_provider_keys:
                    issues.append("multi_no_configured_subproviders")
            elif provider != "log":
                selected = providers.get(provider, {"configured": False, "ready": False})
                selected_ready = bool(selected.get("ready"))
                if not selected.get("configured"):
                    issues.append(f"{provider}_not_configured")
        if settings.push_notification_fail_closed and not settings.push_notifications_enabled:
            issues.append("fail_closed_without_push_enabled")

        device_summary = None
        provider_coverage = None
        delivery_gaps: list[dict] = []
        recent_event_stats = None
        recent_events_sample: list[dict] = []
        if self.db is not None:
            devices = await self._list_tenant_devices(tenant_id=tenant_id)
            device_summary = {
                "total": len(devices),
                "active": sum(1 for device in devices if device.is_active),
                "inactive": sum(1 for device in devices if not device.is_active),
                "by_platform": dict(Counter(self._normalize_platform(device.platform) for device in devices)),
                "miniapp_debug": self._build_miniapp_debug_summary(devices),
            }
            provider_coverage, delivery_gaps = self._assess_provider_coverage(
                provider=provider,
                providers=providers,
                devices=devices,
            )
            recent_events_sample = await self._list_tenant_recent_events(tenant_id=tenant_id, limit=10)
            recent_event_stats = self._summarize_recent_events(recent_events_sample)
            issues.extend(
                gap["issue"]
                for gap in delivery_gaps
                if gap.get("severity") == "error" and gap.get("issue") not in issues
            )

        return {
            "enabled": bool(settings.push_notifications_enabled),
            "provider": provider,
            "fail_closed": bool(settings.push_notification_fail_closed),
            "auto_deactivate_invalid_tokens": bool(settings.push_auto_deactivate_invalid_tokens),
            "ready": True if provider == "log" else bool(settings.push_notifications_enabled) and selected_ready and not issues,
            "issues": issues,
            "providers": providers,
            "active_providers": active_provider_keys,
            "active_provider_readiness": active_provider_readiness,
            "tenant_id": tenant_id,
            "device_summary": device_summary,
            "provider_coverage": provider_coverage,
            "delivery_gaps": delivery_gaps,
            "configuration_sources": self._build_configuration_sources(
                providers=providers,
                fcm_service_account_file=fcm_service_account_file,
                wechat_auth_mode=wechat_auth_mode,
            ),
            "readiness_score": self._compute_readiness_score(
                enabled=bool(settings.push_notifications_enabled),
                provider=provider,
                providers=providers,
                issues=issues,
                delivery_gaps=delivery_gaps,
            ),
            "action_items": self._build_push_action_items(
                provider=provider,
                providers=providers,
                delivery_gaps=delivery_gaps,
            ),
            "recent_event_stats": recent_event_stats,
            "recent_events_sample": recent_events_sample,
            "redis_available": self.redis is not None,
            "provider_diagnostics": self._build_provider_diagnostics(providers),
            "setup_guides": self._build_setup_guides(providers),
        }

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

    async def _list_tenant_devices(self, *, tenant_id: str) -> list[PushDevice]:
        if self.db is None:
            return []
        result = await self.db.execute(
            select(PushDevice)
            .where(PushDevice.tenant_id == tenant_id)
            .order_by(PushDevice.updated_at.desc())
        )
        return list(result.scalars().all())

    async def _list_tenant_recent_events(self, *, tenant_id: str, limit: int = 20) -> list[dict]:
        if self.redis is None or not hasattr(self.redis, "scan"):
            return []

        cursor = 0
        items: list[dict] = []
        pattern = f"push:events:{tenant_id}:*"
        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=100)
            for key in keys or []:
                rows = await self.redis.lrange(key, 0, max(limit - 1, 0))
                for row in rows:
                    try:
                        payload = json.loads(row)
                    except json.JSONDecodeError:
                        continue
                    payload.setdefault("event_scope", "user")
                    payload.setdefault("event_key", key)
                    items.append(payload)
            if cursor == 0 or len(items) >= limit:
                break

        items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return items[:limit]

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

    def _build_miniapp_debug_summary(self, devices: list[PushDevice]) -> dict:
        debug_devices = [device for device in devices if self._normalize_platform(device.platform) == "miniapp-debug"]
        active_devices = [device for device in debug_devices if bool(getattr(device, "is_active", False))]
        latest_seen = max(
            (
                device.last_seen_at or device.updated_at or device.created_at
                for device in debug_devices
                if device.last_seen_at or device.updated_at or device.created_at
            ),
            default=None,
        )
        latest_named = []
        for device in debug_devices[:5]:
            latest_named.append(
                {
                    "device_name": device.device_name,
                    "app_version": device.app_version,
                    "is_active": bool(device.is_active),
                    "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                }
            )
        return {
            "total": len(debug_devices),
            "active": len(active_devices),
            "inactive": max(len(debug_devices) - len(active_devices), 0),
            "latest_seen_at": latest_seen.isoformat() if latest_seen else None,
            "latest_devices": latest_named,
        }

    def _summarize_recent_events(self, events: list[dict]) -> dict:
        status_counts = Counter(str(item.get("status") or "unknown") for item in events)
        provider_counts = Counter()
        for item in events:
            delivery = item.get("delivery") if isinstance(item.get("delivery"), dict) else {}
            providers = delivery.get("providers") if isinstance(delivery.get("providers"), dict) else {}
            if providers:
                provider_counts.update({str(key): int(value or 0) for key, value in providers.items()})
            elif delivery.get("provider"):
                provider_counts.update([str(delivery.get("provider"))])
        return {
            "count": len(events),
            "status_counts": dict(status_counts),
            "provider_counts": dict(provider_counts),
            "latest_timestamp": events[0].get("timestamp") if events else None,
        }

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
        if mode in {"log", "webhook", "fcm", "wechat"}:
            return await self._dispatch_single_provider_async(mode, payload, devices)

        results: list[dict] = []
        grouped = self._group_devices_by_provider(devices)
        if grouped["fcm"]:
            results.extend(await self._dispatch_single_provider_async("fcm", payload, grouped["fcm"]))
        if grouped["wechat"]:
            results.extend(await self._dispatch_single_provider_async("wechat", payload, grouped["wechat"]))
        if grouped["fallback"]:
            results.extend(await self._dispatch_single_provider_async("log", payload, grouped["fallback"]))
        return results

    def _dispatch_multi_sync(self, payload: dict, devices: list[dict]) -> list[dict]:
        mode = (settings.push_notification_provider or "log").lower()
        if mode in {"log", "webhook", "fcm", "wechat"}:
            return self._dispatch_single_provider_sync(mode, payload, devices)

        results: list[dict] = []
        grouped = self._group_devices_by_provider(devices)
        if grouped["fcm"]:
            results.extend(self._dispatch_single_provider_sync("fcm", payload, grouped["fcm"]))
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
        timeout = httpx.Timeout(10.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if self._uses_fcm_v1():
                results: list[dict] = []
                for device in devices:
                    request_payload, headers, endpoint = self._build_fcm_v1_request(payload, device)
                    try:
                        response = await client.post(endpoint, json=request_payload, headers=headers)
                        response.raise_for_status()
                        self.logger.info("push.fcm_response", status_code=response.status_code, response=response.text[:500], token_suffix=self._token_suffix(device.get("device_token")))
                        results.append(self._provider_success("fcm", [device]))
                    except httpx.HTTPStatusError as exc:
                        body = exc.response.text[:1000] if exc.response is not None else ""
                        failure = await self._handle_provider_failure_async("fcm", payload, [device], f"{exc}. body={body}", response=exc.response)
                        results.append(failure)
                    except httpx.HTTPError as exc:
                        results.append(await self._handle_provider_failure_async("fcm", payload, [device], str(exc)))
                return self._collapse_results("fcm", results)

            request_payload, headers, endpoint = self._build_fcm_legacy_request(payload, devices)
            try:
                response = await client.post(endpoint, json=request_payload, headers=headers)
                response.raise_for_status()
                self.logger.info("push.fcm_response", status_code=response.status_code, response=response.text[:500], device_count=len(devices))
                body = response.json()
                return await self._handle_fcm_legacy_response_async(payload, devices, body)
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:1000] if exc.response is not None else ""
                return await self._handle_provider_failure_async("fcm", payload, devices, f"{exc}. body={body}", response=exc.response)
            except (httpx.HTTPError, ValueError) as exc:
                return await self._handle_provider_failure_async("fcm", payload, devices, str(exc))

    def _send_fcm_sync(self, payload: dict, devices: list[dict]) -> dict:
        if not self._fcm_configured():
            return self._provider_not_configured("fcm", payload, devices)
        with httpx.Client(timeout=10.0) as client:
            if self._uses_fcm_v1():
                results: list[dict] = []
                for device in devices:
                    request_payload, headers, endpoint = self._build_fcm_v1_request(payload, device)
                    try:
                        response = client.post(endpoint, json=request_payload, headers=headers)
                        response.raise_for_status()
                        self.logger.info("push.fcm_response", status_code=response.status_code, response=response.text[:500], token_suffix=self._token_suffix(device.get("device_token")))
                        results.append(self._provider_success("fcm", [device]))
                    except httpx.HTTPStatusError as exc:
                        body = exc.response.text[:1000] if exc.response is not None else ""
                        results.append(self._handle_provider_failure_sync("fcm", payload, [device], f"{exc}. body={body}", response=exc.response))
                    except httpx.HTTPError as exc:
                        results.append(self._handle_provider_failure_sync("fcm", payload, [device], str(exc)))
                return self._collapse_results("fcm", results)

            request_payload, headers, endpoint = self._build_fcm_legacy_request(payload, devices)
            try:
                response = client.post(endpoint, json=request_payload, headers=headers)
                response.raise_for_status()
                self.logger.info("push.fcm_response", status_code=response.status_code, response=response.text[:500], device_count=len(devices))
                body = response.json()
                return self._handle_fcm_legacy_response_sync(payload, devices, body)
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:1000] if exc.response is not None else ""
                return self._handle_provider_failure_sync("fcm", payload, devices, f"{exc}. body={body}", response=exc.response)
            except (httpx.HTTPError, ValueError) as exc:
                return self._handle_provider_failure_sync("fcm", payload, devices, str(exc))

    async def _send_wechat_async(self, payload: dict, devices: list[dict]) -> list[dict]:
        if not self._wechat_configured():
            return [self._provider_not_configured("wechat", payload, devices)]
        access_token = await self._get_wechat_access_token_async()
        if not access_token:
            return [self._provider_not_configured("wechat", payload, devices)]
        timeout = httpx.Timeout(10.0, connect=2.0)
        results: list[dict] = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            for device in devices:
                try:
                    response = await client.post(
                        f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}",
                        json={
                            "touser": device["device_token"],
                            "template_id": settings.push_wechat_template_id,
                            "page": settings.push_wechat_page,
                            "miniprogram_state": settings.push_wechat_miniprogram_state,
                            "lang": settings.push_wechat_lang,
                            "data": self._build_wechat_subscribe_data(payload),
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    if self._wechat_body_requires_token_refresh(body):
                        refreshed = await self._retry_wechat_send_after_token_refresh_async(client, payload, device)
                        results.append(refreshed)
                        continue
                    if body.get("errcode", 0) != 0:
                        results.append(await self._handle_provider_failure_async("wechat", payload, [device], body.get("errmsg", "wechat error"), response_body=body))
                    else:
                        results.append(self._provider_success("wechat", [device]))
                except (httpx.HTTPError, ValueError) as exc:
                    results.append(await self._handle_provider_failure_async("wechat", payload, [device], str(exc), response=getattr(exc, "response", None)))
        return results

    def _send_wechat_sync(self, payload: dict, devices: list[dict]) -> list[dict]:
        if not self._wechat_configured():
            return [self._provider_not_configured("wechat", payload, devices)]
        access_token = self._get_wechat_access_token_sync()
        if not access_token:
            return [self._provider_not_configured("wechat", payload, devices)]
        results: list[dict] = []
        with httpx.Client(timeout=10.0) as client:
            for device in devices:
                try:
                    response = client.post(
                        f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}",
                        json={
                            "touser": device["device_token"],
                            "template_id": settings.push_wechat_template_id,
                            "page": settings.push_wechat_page,
                            "miniprogram_state": settings.push_wechat_miniprogram_state,
                            "lang": settings.push_wechat_lang,
                            "data": self._build_wechat_subscribe_data(payload),
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    if self._wechat_body_requires_token_refresh(body):
                        refreshed = self._retry_wechat_send_after_token_refresh_sync(client, payload, device)
                        results.append(refreshed)
                        continue
                    if body.get("errcode", 0) != 0:
                        results.append(self._handle_provider_failure_sync("wechat", payload, [device], body.get("errmsg", "wechat error"), response_body=body))
                    else:
                        results.append(self._provider_success("wechat", [device]))
                except (httpx.HTTPError, ValueError) as exc:
                    results.append(self._handle_provider_failure_sync("wechat", payload, [device], str(exc), response=getattr(exc, "response", None)))
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

    def _build_fcm_v1_request(self, payload: dict, device: dict) -> tuple[dict[str, Any], dict[str, str], str]:
        service_account_file = self._resolve_fcm_service_account_file()
        project_id = self._resolve_fcm_project_id(service_account_file)
        if service_account_file:
            access_token = self._load_fcm_access_token_from_service_account()
            endpoint = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
            body = {
                "message": {
                    "token": device["device_token"],
                    "notification": {"title": payload.get("title"), "body": payload.get("body")},
                    "data": {
                        "status": str(payload.get("status") or ""),
                        "document_id": str(payload.get("document_id") or ""),
                    },
                }
            }
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            return body, headers, endpoint

        endpoint = f"https://fcm.googleapis.com/v1/projects/{settings.push_fcm_project_id}/messages:send"
        body = {
            "message": {
                "token": device["device_token"],
                "notification": {"title": payload.get("title"), "body": payload.get("body")},
                "data": {
                    "status": str(payload.get("status") or ""),
                    "document_id": str(payload.get("document_id") or ""),
                },
            }
        }
        headers = {"Authorization": f"Bearer {settings.push_fcm_access_token}", "Content-Type": "application/json"}
        return body, headers, endpoint

    def _build_fcm_legacy_request(self, payload: dict, devices: list[dict]) -> tuple[dict[str, Any], dict[str, str], str]:
        tokens = [device["device_token"] for device in devices]
        endpoint = settings.push_fcm_endpoint

        body = {
            "registration_ids": tokens,
            "notification": {"title": payload.get("title"), "body": payload.get("body")},
            "data": {"status": payload.get("status"), "document_id": payload.get("document_id")},
        }
        headers = {"Authorization": f"key={settings.push_fcm_server_key}", "Content-Type": "application/json"}
        return body, headers, endpoint

    def _uses_fcm_v1(self) -> bool:
        return bool(
            (self._resolve_fcm_service_account_file() and self._resolve_fcm_project_id(self._resolve_fcm_service_account_file()))
            or (settings.push_fcm_access_token and settings.push_fcm_project_id)
        )

    async def _handle_fcm_legacy_response_async(self, payload: dict, devices: list[dict], body: dict[str, Any]) -> dict:
        failed_devices = self._extract_fcm_legacy_failed_devices(devices, body)
        invalid_devices = [item for item in failed_devices if self._looks_like_invalid_token("fcm", item.get("error", ""), body)]
        if invalid_devices:
            await self._deactivate_devices_async(payload, invalid_devices, provider="fcm", reason="invalid_registration_token")
        results = [self._provider_success("fcm", [device]) for device in devices if device not in failed_devices]
        for failure in failed_devices:
            results.append(self._provider_failure("fcm", [failure], str(failure.get("error") or "delivery failed")))
        return self._collapse_results("fcm", results)

    def _handle_fcm_legacy_response_sync(self, payload: dict, devices: list[dict], body: dict[str, Any]) -> dict:
        failed_devices = self._extract_fcm_legacy_failed_devices(devices, body)
        invalid_devices = [item for item in failed_devices if self._looks_like_invalid_token("fcm", item.get("error", ""), body)]
        if invalid_devices:
            self._deactivate_devices_sync(payload, invalid_devices, provider="fcm", reason="invalid_registration_token")
        results = [self._provider_success("fcm", [device]) for device in devices if device not in failed_devices]
        for failure in failed_devices:
            results.append(self._provider_failure("fcm", [failure], str(failure.get("error") or "delivery failed")))
        return self._collapse_results("fcm", results)

    def _extract_fcm_legacy_failed_devices(self, devices: list[dict], body: dict[str, Any]) -> list[dict]:
        failures: list[dict] = []
        results = body.get("results")
        if not isinstance(results, list):
            return failures
        for index, result in enumerate(results):
            if not isinstance(result, dict):
                continue
            error = result.get("error")
            if not error:
                continue
            if index >= len(devices):
                continue
            failure = dict(devices[index])
            failure["error"] = str(error)
            failures.append(failure)
        return failures

    async def _handle_provider_failure_async(
        self,
        provider: str,
        payload: dict,
        devices: list[dict],
        error: str,
        *,
        response: httpx.Response | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> dict:
        if self._looks_like_invalid_token(provider, error, response_body, response=response):
            await self._deactivate_devices_async(payload, devices, provider=provider, reason="invalid_device_token")
        return self._provider_failure(provider, devices, error)

    def _handle_provider_failure_sync(
        self,
        provider: str,
        payload: dict,
        devices: list[dict],
        error: str,
        *,
        response: httpx.Response | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> dict:
        if self._looks_like_invalid_token(provider, error, response_body, response=response):
            self._deactivate_devices_sync(payload, devices, provider=provider, reason="invalid_device_token")
        return self._provider_failure(provider, devices, error)

    def _looks_like_invalid_token(
        self,
        provider: str,
        error: str,
        response_body: dict[str, Any] | None = None,
        *,
        response: httpx.Response | None = None,
    ) -> bool:
        if not settings.push_auto_deactivate_invalid_tokens:
            return False
        lowered = str(error or "").lower()
        if provider == "fcm":
            if any(code in lowered for code in self.INVALID_FCM_CODES):
                return True
            body = response_body or self._safe_json(response)
            return self._fcm_body_has_invalid_token(body)
        if provider == "wechat":
            body = response_body or self._safe_json(response)
            errcode = int((body or {}).get("errcode") or 0)
            return errcode in self.INVALID_WECHAT_CODES
        return False

    def _fcm_body_has_invalid_token(self, body: dict[str, Any] | None) -> bool:
        if not isinstance(body, dict):
            return False
        detail_list = (((body.get("error") or {}).get("details")) if isinstance(body.get("error"), dict) else None) or []
        for detail in detail_list:
            if not isinstance(detail, dict):
                continue
            code = str(detail.get("errorCode") or "").lower()
            if code in self.INVALID_FCM_CODES:
                return True
        code = str((body.get("error") or {}).get("status") or "").lower() if isinstance(body.get("error"), dict) else ""
        message = str((body.get("error") or {}).get("message") or "").lower() if isinstance(body.get("error"), dict) else ""
        return any(item in code or item in message for item in self.INVALID_FCM_CODES)

    async def _deactivate_devices_async(self, payload: dict, devices: list[dict], *, provider: str, reason: str) -> None:
        if self.db is None:
            return
        tokens = [str(device.get("device_token") or "").strip() for device in devices if str(device.get("device_token") or "").strip()]
        if not tokens:
            return
        result = await self.db.execute(
            select(PushDevice).where(
                and_(
                    PushDevice.tenant_id == payload.get("tenant_id"),
                    PushDevice.user_id == payload.get("user_id"),
                    PushDevice.device_token.in_(tokens),
                    PushDevice.is_active.is_(True),
                )
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for row in rows:
            row.is_active = False
            row.updated_at = now
        await self.db.flush()
        self.logger.warning(
            "push.invalid_tokens_deactivated",
            provider=provider,
            reason=reason,
            tenant_id=payload.get("tenant_id"),
            user_id=payload.get("user_id"),
            device_count=len(rows),
            token_suffixes=[self._token_suffix(row.device_token) for row in rows],
        )

    def _deactivate_devices_sync(self, payload: dict, devices: list[dict], *, provider: str, reason: str) -> None:
        tokens = [str(device.get("device_token") or "").strip() for device in devices if str(device.get("device_token") or "").strip()]
        if not tokens:
            return
        conn = psycopg2.connect(settings.postgres_dsn_sync)
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE push_devices
                    SET is_active = FALSE, updated_at = %s
                    WHERE tenant_id = %s AND user_id = %s AND is_active = TRUE AND device_token = ANY(%s)
                    """,
                    (now, payload.get("tenant_id"), payload.get("user_id"), tokens),
                )
            conn.commit()
            self.logger.warning(
                "push.invalid_tokens_deactivated",
                provider=provider,
                reason=reason,
                tenant_id=payload.get("tenant_id"),
                user_id=payload.get("user_id"),
                device_count=len(tokens),
                token_suffixes=[self._token_suffix(token) for token in tokens],
            )
        finally:
            conn.close()

    def _safe_json(self, response: httpx.Response | None) -> dict[str, Any] | None:
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _token_suffix(self, token: str | None) -> str:
        value = str(token or "")
        return value[-8:] if len(value) > 8 else value

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
        groups = {"fcm": [], "wechat": [], "fallback": []}
        for device in devices:
            platform = self._normalize_platform(device.get("platform"))
            if platform in self.FCM_PLATFORMS:
                groups["fcm"].append(device)
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

    def _wechat_configured(self) -> bool:
        return bool(self._resolve_wechat_auth_mode() in {"access_token", "app_secret"} and settings.push_wechat_template_id)

    def _build_provider_next_step(self, provider: str, meta: dict[str, Any]) -> str:
        if provider == "log":
            return "当前为日志模式，仅用于本地联调。"
        if bool(meta.get("ready")):
            return "运行凭据已到位，可直接联调真实推送。"
        missing_env_vars = meta.get("missing_env_vars") if isinstance(meta.get("missing_env_vars"), list) else []
        if provider == "fcm":
            if missing_env_vars:
                return "补齐 Firebase 凭据后即可切到真实 FCM 推送。"
            return "检查 FCM project_id、access token 或 service account 文件是否有效。"
        if provider == "wechat":
            if missing_env_vars:
                return "补齐小程序 access token 或 appid/appsecret，以及订阅消息模板 ID 后即可联调微信通知。"
            return "检查小程序订阅消息模板、access token 或 appid/appsecret 与用户 openid 是否有效。"
        if provider == "webhook":
            return "补齐 webhook 地址后即可联调外部推送网关。"
        return "检查 provider 配置与运行凭据。"

    def _build_provider_diagnostics(self, providers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        diagnostics: dict[str, dict[str, Any]] = {}
        for provider_name, meta in providers.items():
            diagnostics[provider_name] = {
                "implemented": bool(meta.get("implemented", provider_name in {"log", "webhook"})),
                "configured": bool(meta.get("configured")),
                "ready": bool(meta.get("ready")),
                "code_ready": bool(meta.get("code_ready", meta.get("implemented", True))),
                "missing_env_vars": list(meta.get("missing_env_vars") or []),
                "required_env_vars": list(meta.get("required_env_vars") or []),
                "transport": meta.get("transport"),
                "delivery_mode": meta.get("delivery_mode"),
                "supports_platforms": list(meta.get("supports_platforms") or []),
                "next_step": meta.get("next_step"),
                "env_examples": self._env_examples_for_provider(provider_name),
                "secret_targets": self._secret_targets_for_provider(provider_name),
            }
            if provider_name == "fcm":
                diagnostics[provider_name]["project_id"] = meta.get("project_id")
                diagnostics[provider_name]["service_account_file_configured"] = bool(meta.get("service_account_file_configured"))
            if provider_name == "wechat":
                diagnostics[provider_name]["endpoint"] = meta.get("endpoint")
                diagnostics[provider_name]["template_id_configured"] = bool(meta.get("template_id_configured"))
        return diagnostics

    def _build_setup_guides(self, providers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        guides: dict[str, dict[str, Any]] = {}
        for provider_name in ("fcm", "wechat", "webhook"):
            meta = providers.get(provider_name, {})
            guides[provider_name] = {
                "configured": bool(meta.get("configured")),
                "ready": bool(meta.get("ready")),
                "required_env_vars": list(meta.get("required_env_vars") or []),
                "missing_env_vars": list(meta.get("missing_env_vars") or []),
                "env_examples": self._env_examples_for_provider(provider_name),
                "secret_targets": self._secret_targets_for_provider(provider_name),
                "docker_mount_dir": "/run/secrets/docmind",
                "next_step": meta.get("next_step"),
            }
        return guides

    def _build_configuration_sources(
        self,
        *,
        providers: dict[str, dict[str, Any]],
        fcm_service_account_file: str | None,
        wechat_auth_mode: str,
    ) -> dict[str, dict[str, Any]]:
        fcm_source = "service_account_file" if fcm_service_account_file else "access_token" if settings.push_fcm_access_token else "server_key" if settings.push_fcm_server_key else "none"
        wechat_source = wechat_auth_mode if wechat_auth_mode in {"access_token", "app_secret"} else "none"
        return {
            "fcm": {
                "source": fcm_source,
                "configured": bool(providers.get("fcm", {}).get("configured")),
                "detail": str(fcm_service_account_file or settings.push_fcm_project_id or "").strip() or None,
            },
            "wechat": {
                "source": wechat_source,
                "configured": bool(providers.get("wechat", {}).get("configured")),
                "detail": str(settings.push_wechat_app_id or "").strip() or None,
            },
            "webhook": {
                "source": "env" if settings.push_notification_webhook_url else "none",
                "configured": bool(providers.get("webhook", {}).get("configured")),
                "detail": str(settings.push_notification_webhook_url or "").strip() or None,
            },
        }

    def _compute_readiness_score(
        self,
        *,
        enabled: bool,
        provider: str,
        providers: dict[str, dict[str, Any]],
        issues: list[str],
        delivery_gaps: list[dict],
    ) -> int:
        if not enabled:
            return 0
        score = 100
        if provider == "multi":
            for provider_name in ("fcm", "wechat"):
                if not providers.get(provider_name, {}).get("configured"):
                    score -= 10
        elif provider != "log" and not providers.get(provider, {}).get("ready"):
            score -= 40
        score -= sum(20 for gap in delivery_gaps if gap.get("severity") == "error")
        score -= sum(10 for gap in delivery_gaps if gap.get("severity") == "warning")
        score -= min(len(issues) * 5, 25)
        return max(0, min(100, score))

    def _build_push_action_items(
        self,
        *,
        provider: str,
        providers: dict[str, dict[str, Any]],
        delivery_gaps: list[dict],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for provider_name in ("fcm", "wechat", "webhook"):
            meta = providers.get(provider_name, {})
            missing = list(meta.get("missing_env_vars") or [])
            if missing:
                items.append(
                    {
                        "category": "provider_config",
                        "provider": provider_name,
                        "severity": "high" if provider_name == "wechat" else "medium",
                        "message": f"{provider_name} 仍缺少关键配置: {', '.join(missing)}",
                        "next_step": meta.get("next_step"),
                        "env_examples": self._env_examples_for_provider(provider_name),
                        "secret_targets": self._secret_targets_for_provider(provider_name),
                    }
                )
        for gap in delivery_gaps:
            items.append(
                {
                    "category": "delivery_gap",
                    "provider": gap.get("required_provider"),
                    "platform": gap.get("platform"),
                    "severity": gap.get("severity") or "warning",
                    "message": gap.get("recommendation") or gap.get("issue") or "delivery_gap",
                    "next_step": gap.get("recommendation"),
                }
            )
        if provider == "multi" and not any(providers.get(name, {}).get("configured") for name in ("fcm", "wechat")):
            items.append(
                {
                    "category": "provider_config",
                    "provider": "multi",
                    "severity": "high",
                    "message": "multi 模式下尚未配置任何真实推送 provider。",
                    "next_step": "至少完成 FCM 或微信中的一个 provider 配置。",
                }
            )
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            key = (str(item.get("category")), str(item.get("provider")), str(item.get("message")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:20]

    def _env_examples_for_provider(self, provider: str) -> list[str]:
        if provider == "fcm":
            return [
                "PUSH_FCM_SERVICE_ACCOUNT_FILE=/run/secrets/docmind/firebase-service-account.json",
                "PUSH_FCM_ACCESS_TOKEN=<token>",
                "PUSH_FCM_PROJECT_ID=<firebase-project-id>",
            ]
        if provider == "wechat":
            return [
                "PUSH_WECHAT_APP_ID=wx1234567890",
                "PUSH_WECHAT_APP_SECRET=<miniapp-secret>",
                "PUSH_WECHAT_TEMPLATE_ID=<subscribe-template-id>",
                "PUSH_WECHAT_ACCESS_TOKEN=<optional-direct-access-token>",
            ]
        if provider == "webhook":
            return ["PUSH_NOTIFICATION_WEBHOOK_URL=https://push-gateway.example.com/webhook"]
        return []

    def _secret_targets_for_provider(self, provider: str) -> list[dict[str, str]]:
        if provider == "fcm":
            return [
                {
                    "host_path_hint": "secrets/firebase-service-account.json",
                    "container_path": "/run/secrets/docmind/firebase-service-account.json",
                    "description": "Firebase service account JSON",
                }
            ]
        return []

    def _normalize_platform(self, platform: str | None) -> str:
        return str(platform or "unknown").strip().lower()

    def _build_wechat_subscribe_data(self, payload: dict[str, Any]) -> dict[str, dict[str, str]]:
        timestamp = self._format_wechat_time(payload.get("timestamp"))
        date_only = self._format_wechat_date(payload.get("timestamp"))
        status = self._format_wechat_phrase(payload.get("status") or payload.get("result") or "已完成")
        title = self._format_wechat_thing(payload.get("title") or "DocMind通知")
        body = self._format_wechat_thing(payload.get("body") or "您有一条新消息")
        identifier = self._format_wechat_character_string(
            payload.get("document_id") or payload.get("task_id") or payload.get("event_id") or payload.get("status") or "DOCMIND"
        )
        return {
            "character_string1": {"value": identifier},
            "thing2": {"value": title},
            "thing3": {"value": body},
            "phrase4": {"value": status},
            "time5": {"value": timestamp},
            "date5": {"value": date_only},
        }

    def _format_wechat_character_string(self, value: Any) -> str:
        normalized = "".join(ch for ch in str(value or "DOCMIND") if ch.isascii() and (ch.isalnum() or ch in "-_#/.:"))
        normalized = normalized[:32]
        return normalized or "DOCMIND"

    def _format_wechat_thing(self, value: Any) -> str:
        text = " ".join(str(value or "").split())
        return text[:20] or "DocMind通知"

    def _format_wechat_phrase(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        mapped = {
            "test": "已发送",
            "ready": "已完成",
            "completed": "已完成",
            "success": "成功",
            "ok": "成功",
            "failed": "失败",
            "error": "失败",
            "running": "处理中",
            "processing": "处理中",
            "pending": "待处理",
        }.get(raw)
        if mapped:
            return mapped
        text = " ".join(str(value or "").split())
        return text[:5] or "已完成"

    def _format_wechat_time(self, value: Any) -> str:
        dt = self._coerce_wechat_datetime(value)
        return dt.strftime("%Y-%m-%d %H:%M")

    def _format_wechat_date(self, value: Any) -> str:
        dt = self._coerce_wechat_datetime(value)
        return dt.strftime("%Y-%m-%d")

    def _coerce_wechat_datetime(self, value: Any) -> datetime:
        raw = str(value or "").strip()
        if raw:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    return dt.astimezone()
                return dt
            except ValueError:
                pass
        return datetime.now()

    def _wechat_body_requires_token_refresh(self, body: dict[str, Any] | None) -> bool:
        if not isinstance(body, dict):
            return False
        try:
            errcode = int(body.get("errcode") or 0)
        except (TypeError, ValueError):
            return False
        return errcode in self.WECHAT_TOKEN_REFRESH_CODES

    async def _clear_wechat_token_cache_async(self) -> None:
        if self.redis is not None:
            await self.redis.delete(self._wechat_token_cache_key())

    def _clear_wechat_token_cache_sync(self) -> None:
        if self.redis is not None:
            sync_delete = getattr(self.redis, "delete", None)
            if sync_delete is not None and not inspect.iscoroutinefunction(sync_delete):
                sync_delete(self._wechat_token_cache_key())

    async def _retry_wechat_send_after_token_refresh_async(self, client: httpx.AsyncClient, payload: dict, device: dict) -> dict:
        await self._clear_wechat_token_cache_async()
        access_token = await self._get_wechat_access_token_async()
        if not access_token:
            return await self._handle_provider_failure_async("wechat", payload, [device], "wechat access_token refresh failed")
        response = await client.post(
            f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}",
            json={
                "touser": device["device_token"],
                "template_id": settings.push_wechat_template_id,
                "page": settings.push_wechat_page,
                "miniprogram_state": settings.push_wechat_miniprogram_state,
                "lang": settings.push_wechat_lang,
                "data": self._build_wechat_subscribe_data(payload),
            },
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errcode", 0) != 0:
            return await self._handle_provider_failure_async("wechat", payload, [device], body.get("errmsg", "wechat error"), response_body=body)
        return self._provider_success("wechat", [device])

    def _retry_wechat_send_after_token_refresh_sync(self, client: httpx.Client, payload: dict, device: dict) -> dict:
        self._clear_wechat_token_cache_sync()
        access_token = self._get_wechat_access_token_sync()
        if not access_token:
            return self._handle_provider_failure_sync("wechat", payload, [device], "wechat access_token refresh failed")
        response = client.post(
            f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={access_token}",
            json={
                "touser": device["device_token"],
                "template_id": settings.push_wechat_template_id,
                "page": settings.push_wechat_page,
                "miniprogram_state": settings.push_wechat_miniprogram_state,
                "lang": settings.push_wechat_lang,
                "data": self._build_wechat_subscribe_data(payload),
            },
        )
        response.raise_for_status()
        body = response.json()
        if body.get("errcode", 0) != 0:
            return self._handle_provider_failure_sync("wechat", payload, [device], body.get("errmsg", "wechat error"), response_body=body)
        return self._provider_success("wechat", [device])

    def _required_push_env_vars(self, provider: str) -> list[str]:
        if provider == "fcm":
            return [
                "PUSH_FCM_SERVICE_ACCOUNT_FILE or PUSH_FCM_ACCESS_TOKEN + PUSH_FCM_PROJECT_ID",
                "PUSH_FCM_SERVER_KEY (legacy optional)",
            ]
        if provider == "wechat":
            return ["PUSH_WECHAT_ACCESS_TOKEN or PUSH_WECHAT_APP_ID + PUSH_WECHAT_APP_SECRET", "PUSH_WECHAT_TEMPLATE_ID"]
        return []

    def _missing_push_env_vars(self, provider: str, fcm_service_account_file: str | None = None) -> list[str]:
        if provider == "fcm":
            has_service_account = bool(fcm_service_account_file and self._resolve_fcm_project_id(fcm_service_account_file))
            has_v1 = bool(settings.push_fcm_access_token and settings.push_fcm_project_id)
            has_legacy = bool(settings.push_fcm_server_key)
            if has_service_account or has_v1 or has_legacy:
                return []
            return ["PUSH_FCM_SERVICE_ACCOUNT_FILE", "PUSH_FCM_ACCESS_TOKEN", "PUSH_FCM_PROJECT_ID"]
        if provider == "wechat":
            missing = []
            if self._resolve_wechat_auth_mode() == "none":
                missing.append("PUSH_WECHAT_ACCESS_TOKEN")
                missing.append("PUSH_WECHAT_APP_ID")
                missing.append("PUSH_WECHAT_APP_SECRET")
            if not settings.push_wechat_template_id:
                missing.append("PUSH_WECHAT_TEMPLATE_ID")
            return missing
        return []

    def _resolve_wechat_auth_mode(self) -> str:
        if str(settings.push_wechat_access_token or "").strip():
            return "access_token"
        if str(settings.push_wechat_app_id or "").strip() and str(settings.push_wechat_app_secret or "").strip():
            return "app_secret"
        return "none"

    def _wechat_token_cache_key(self) -> str:
        app_id = str(settings.push_wechat_app_id or "default").strip() or "default"
        return f"{self.WECHAT_TOKEN_CACHE_KEY_PREFIX}{app_id}"

    async def _get_wechat_access_token_async(self) -> str:
        direct = str(settings.push_wechat_access_token or "").strip()
        if direct:
            return direct
        if self.redis is not None:
            cached = await self.redis.get(self._wechat_token_cache_key())
            if cached:
                return str(cached).strip()
        if self._resolve_wechat_auth_mode() != "app_secret":
            return ""
        timeout = httpx.Timeout(10.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.weixin.qq.com/cgi-bin/stable_token",
                json={
                    "grant_type": "client_credential",
                    "appid": settings.push_wechat_app_id,
                    "secret": settings.push_wechat_app_secret,
                    "force_refresh": False,
                },
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("access_token"):
                fallback = await client.get(
                    "https://api.weixin.qq.com/cgi-bin/token",
                    params={
                        "grant_type": "client_credential",
                        "appid": settings.push_wechat_app_id,
                        "secret": settings.push_wechat_app_secret,
                    },
                )
                fallback.raise_for_status()
                body = fallback.json()
        token = str(body.get("access_token") or "").strip()
        if not token:
            raise ValueError(str(body.get("errmsg") or "wechat access_token missing"))
        if self.redis is not None:
            expires_in = int(body.get("expires_in") or 7200)
            await self.redis.set(self._wechat_token_cache_key(), token, ex=max(expires_in - 300, 60))
        return token

    def _get_wechat_access_token_sync(self) -> str:
        direct = str(settings.push_wechat_access_token or "").strip()
        if direct:
            return direct
        if self._resolve_wechat_auth_mode() != "app_secret":
            return ""
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                "https://api.weixin.qq.com/cgi-bin/stable_token",
                json={
                    "grant_type": "client_credential",
                    "appid": settings.push_wechat_app_id,
                    "secret": settings.push_wechat_app_secret,
                    "force_refresh": False,
                },
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("access_token"):
                fallback = client.get(
                    "https://api.weixin.qq.com/cgi-bin/token",
                    params={
                        "grant_type": "client_credential",
                        "appid": settings.push_wechat_app_id,
                        "secret": settings.push_wechat_app_secret,
                    },
                )
                fallback.raise_for_status()
                body = fallback.json()
        token = str(body.get("access_token") or "").strip()
        if not token:
            raise ValueError(str(body.get("errmsg") or "wechat access_token missing"))
        return token

    def _assess_provider_coverage(
        self,
        *,
        provider: str,
        providers: dict[str, dict],
        devices: list[PushDevice],
    ) -> tuple[dict[str, dict], list[dict]]:
        platform_counts = Counter(
            self._normalize_platform(device.platform)
            for device in devices
            if bool(getattr(device, "is_active", False))
        )
        required_by_platform = {
            "android": "fcm",
            "wechat": "wechat",
            "weapp": "wechat",
            "miniapp": "wechat",
            "miniprogram": "wechat",
        }

        provider_coverage: dict[str, dict] = {}
        gaps: list[dict] = []
        for platform_name, count in sorted(platform_counts.items()):
            required_provider = required_by_platform.get(platform_name)
            if required_provider is None:
                provider_coverage[platform_name] = {
                    "device_count": count,
                    "required_provider": None,
                    "provider_ready": provider == "log",
                    "delivery_mode": "log_only" if provider == "log" else "unknown_platform",
                }
                continue

            provider_meta = providers.get(required_provider, {})
            ready = bool(provider_meta.get("ready"))
            if provider == "multi":
                enabled_for_platform = ready
                delivery_mode = "multi"
            elif provider == required_provider:
                enabled_for_platform = ready
                delivery_mode = "direct"
            elif provider == "log":
                enabled_for_platform = True
                delivery_mode = "log_only"
            else:
                enabled_for_platform = False
                delivery_mode = "unsupported_provider_mode"

            provider_coverage[platform_name] = {
                "device_count": count,
                "required_provider": required_provider,
                "provider_ready": ready,
                "delivery_mode": delivery_mode,
                "deliverable": enabled_for_platform,
            }

            if enabled_for_platform:
                continue

            severity = "error" if settings.push_notification_fail_closed else "warning"
            if not ready:
                issue = f"{required_provider}_required_for_{platform_name}"
                recommendation = f"检测到 {count} 台 {platform_name} 设备，请补齐 {required_provider} 推送配置。"
            else:
                issue = f"{provider}_cannot_deliver_{platform_name}"
                recommendation = (
                    f"当前 provider={provider} 无法覆盖 {platform_name} 设备，"
                    f"请切换到 {required_provider} 或 multi 模式。"
                )
            gaps.append(
                {
                    "platform": platform_name,
                    "device_count": count,
                    "required_provider": required_provider,
                    "configured_provider": provider,
                    "issue": issue,
                    "severity": severity,
                    "recommendation": recommendation,
                }
            )

        return provider_coverage, gaps

    def _serialize_device(self, device: PushDevice) -> dict:
        return {
            "platform": self._normalize_platform(device.platform),
            "device_token": device.device_token,
            "device_name": device.device_name,
            "app_version": device.app_version,
        }

    def _serialize_device_record(self, device: PushDevice) -> dict:
        return {
            "id": device.id,
            "tenant_id": device.tenant_id,
            "user_id": device.user_id,
            "platform": self._normalize_platform(device.platform),
            "device_token": device.device_token,
            "device_name": device.device_name,
            "app_version": device.app_version,
            "is_active": bool(device.is_active),
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        }
