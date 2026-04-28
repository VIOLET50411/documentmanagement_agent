"""Startup bootstrap helpers."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.db.user import User, UserMemory
from app.services.auth_service import pwd_context


async def ensure_bootstrap_state(session_factory: async_sessionmaker) -> None:
    """Create demo bootstrap records so the app is usable on first start."""
    logger = structlog.get_logger("docmind.bootstrap")

    async with session_factory() as session:
        result = await session.execute(select(User).where(User.username == settings.bootstrap_demo_admin_username))
        admin = result.scalar_one_or_none()

        if admin is None and settings.bootstrap_demo_admin_enabled:
            admin = User(
                tenant_id=settings.bootstrap_demo_admin_tenant_id,
                username=settings.bootstrap_demo_admin_username,
                email=settings.bootstrap_demo_admin_email,
                hashed_password=pwd_context.hash(settings.bootstrap_demo_admin_password),
                role="ADMIN",
                department=settings.bootstrap_demo_admin_department,
                level=9,
                is_active=True,
                email_verified=True,
            )
            session.add(admin)
            await session.flush()
            logger.info("bootstrap.demo_admin_created", username=admin.username, tenant_id=admin.tenant_id)
        elif admin is not None and settings.bootstrap_demo_admin_enabled:
            updated = False
            if not pwd_context.verify(settings.bootstrap_demo_admin_password, admin.hashed_password):
                admin.hashed_password = pwd_context.hash(settings.bootstrap_demo_admin_password)
                updated = True
            if admin.email != settings.bootstrap_demo_admin_email:
                admin.email = settings.bootstrap_demo_admin_email
                updated = True
            if admin.tenant_id != settings.bootstrap_demo_admin_tenant_id:
                admin.tenant_id = settings.bootstrap_demo_admin_tenant_id
                updated = True
            if admin.department != settings.bootstrap_demo_admin_department:
                admin.department = settings.bootstrap_demo_admin_department
                updated = True
            if admin.role != "ADMIN":
                admin.role = "ADMIN"
                updated = True
            if admin.level != 9:
                admin.level = 9
                updated = True
            if not admin.email_verified:
                admin.email_verified = True
                updated = True
            if not admin.is_active:
                admin.is_active = True
                updated = True
            if updated:
                logger.info("bootstrap.demo_admin_reconciled", username=admin.username, tenant_id=admin.tenant_id)

        if admin is not None:
            defaults = [
                ("answer_style", "prefer_concise_citations", "优先给出结论，再列出依据与引用。"),
                ("focus_domain", "enterprise_docs", "常用企业管理制度、合规制度、流程规范文档。"),
            ]
            for memory_type, key, value in defaults:
                exists = await session.execute(
                    select(UserMemory).where(UserMemory.user_id == admin.id, UserMemory.key == key)
                )
                if exists.scalar_one_or_none() is None:
                    session.add(
                        UserMemory(
                            user_id=admin.id,
                            tenant_id=admin.tenant_id,
                            memory_type=memory_type,
                            key=key,
                            value=value,
                            confidence=0.95,
                        )
                    )

        await session.commit()
