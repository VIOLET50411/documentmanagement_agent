"""DLP watermark forensics service."""

from __future__ import annotations

import json

from app.security.watermark import Watermarker
from app.services.security_audit_service import SecurityAuditService


class DLPForensicsService:
    def __init__(self, redis_client, db=None):
        self.redis = redis_client
        self.db = db
        self.watermarker = Watermarker()

    @staticmethod
    def _key(tenant_id: str, fingerprint: str) -> str:
        return f"dlp:watermark:{tenant_id}:{fingerprint}"

    async def record_issue(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        message_id: str,
        fingerprint: str,
        timestamp: str,
    ) -> None:
        payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "message_id": message_id,
            "fingerprint": fingerprint,
            "timestamp": timestamp,
        }
        if self.redis is not None:
            await self.redis.set(self._key(tenant_id, fingerprint), json.dumps(payload, ensure_ascii=False), ex=180 * 24 * 3600)

        if self.db is not None:
            await SecurityAuditService(self.redis, self.db).log_event(
                tenant_id,
                "watermark_issued",
                "low",
                f"watermark issued for message {message_id}",
                user_id=user_id,
                target=message_id,
                result="ok",
                metadata={"fingerprint": fingerprint, "thread_id": thread_id},
            )

    async def trace_by_fingerprint(self, *, tenant_id: str, fingerprint: str) -> dict | None:
        if self.redis is None:
            return None
        raw = await self.redis.get(self._key(tenant_id, fingerprint))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def trace_from_text(self, *, tenant_id: str, text: str) -> dict | None:
        fingerprint = self.watermarker.extract(text)
        if not fingerprint:
            return None
        result = await self.trace_by_fingerprint(tenant_id=tenant_id, fingerprint=fingerprint)
        if result is None:
            return {"fingerprint": fingerprint, "found": False}
        result["found"] = True
        return result
