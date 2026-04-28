"""Local-first transactional email service abstraction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog


class EmailService:
    """Write email payloads to disk in development; keep provider interface stable."""

    def __init__(self, outbox_dir: str | None = None):
        base_dir = Path(outbox_dir or Path(__file__).resolve().parents[2] / "runtime" / "email_outbox")
        base_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_dir = base_dir
        self.logger = structlog.get_logger("docmind.email")

    async def send_verification_code(self, *, email: str, code: str, tenant_id: str) -> str:
        subject = "DocMind 邮箱验证码"
        body = f"您的验证码是 {code}，10 分钟内有效。租户：{tenant_id}。"
        return self._write_email(email=email, subject=subject, body=body, category="verification")

    async def send_invitation(self, *, email: str, token: str, tenant_id: str, role: str) -> str:
        subject = "DocMind 邀请链接"
        body = (
            "您已收到 DocMind 企业系统邀请。"
            f" 租户：{tenant_id}，角色：{role}。"
            f" 注册时请填写邀请令牌：{token}。"
        )
        return self._write_email(email=email, subject=subject, body=body, category="invitation")

    async def send_password_reset(self, *, email: str, token: str) -> str:
        subject = "DocMind 密码重置"
        body = f"您的密码重置令牌为：{token}。请尽快完成密码重置。"
        return self._write_email(email=email, subject=subject, body=body, category="password_reset")

    def _write_email(self, *, email: str, subject: str, body: str, category: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.outbox_dir / f"{category}_{timestamp}.json"
        payload = {
            "to": email,
            "subject": subject,
            "body": body,
            "category": category,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logger.info("email.queued", email=email, category=category, path=str(path))
        return str(path)
