"""Push notification registration and delivery service."""

from __future__ import annotations

import json
import inspect
from datetime import datetime, timezone

import httpx
import psycopg2
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.push_device import PushDevice


class PushNotificationService:
    def __init__(self, db: AsyncSession | None = None, redis_client=None):
        self.db = db
        self.redis = redis_client

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
        if existing is not None:
            existing.platform = platform
            existing.device_name = device_name
            existing.app_version = app_version
            existing.is_active = True
            existing.last_seen_at = now
            return existing

        device = PushDevice(
            tenant_id=tenant_id,
            user_id=user_id,
            platform=platform,
            device_token=device_token,
            device_name=device_name,
            app_version=app_version,
            is_active=True,
            last_seen_at=now,
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
            structlog.get_logger("docmind.push").warning(
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
        self._record_notification_sync(payload)
        self._dispatch_sync(payload)
        return {"sent": len(devices), "provider": settings.push_notification_provider}

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
                        "platform": row[0],
                        "device_token": row[1],
                        "device_name": row[2],
                        "app_version": row[3],
                    }
                    for row in rows
                ]
        finally:
            conn.close()

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

    def _dispatch_sync(self, payload: dict) -> None:
        provider = (settings.push_notification_provider or "log").lower()
        if provider == "webhook" and settings.push_notification_webhook_url:
            try:
                with httpx.Client(timeout=10.0) as client:
                    client.post(settings.push_notification_webhook_url, json=payload).raise_for_status()
            except httpx.HTTPError as exc:
                structlog.get_logger("docmind.push").warning(
                    "push.dispatch_failed",
                    provider=provider,
                    error=str(exc),
                    tenant_id=payload.get("tenant_id"),
                    user_id=payload.get("user_id"),
                )
                return
            return

        structlog.get_logger("docmind.push").info(
            "push.dispatch_log",
            provider=provider,
            tenant_id=payload.get("tenant_id"),
            user_id=payload.get("user_id"),
            device_count=len(payload.get("devices") or []),
            payload=payload,
        )
