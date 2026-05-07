"""Auth service: authentication, invitations, verification, and token management."""

from __future__ import annotations

import random
import secrets
import string
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.auth import EmailVerificationCode, PasswordResetToken, UserInvitation
from app.models.db.user import User
from app.services.email_service import EmailService

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

ROLE_DEFAULT_LEVEL = {
    "VIEWER": 1,
    "EMPLOYEE": 2,
    "MANAGER": 5,
    "ADMIN": 9,
}


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.email_service = EmailService()

    async def authenticate(self, username: str, password: str) -> User | None:
        result = await self.db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if not pwd_context.verify(password, user.hashed_password):
            return None
        if not user.email_verified and not user.email.endswith("@docmind.local"):
            raise ValueError("邮箱尚未验证")
        return user

    async def register(self, user_data) -> User:
        self._validate_email_domain(user_data.email)

        duplicated = await self.db.execute(
            select(User).where(or_(User.username == user_data.username, User.email == user_data.email))
        )
        if duplicated.scalar_one_or_none() is not None:
            raise ValueError("用户名或邮箱已存在")

        invite = None
        if not settings.auth_allow_public_registration:
            if not user_data.invite_token:
                raise ValueError("当前仅支持邀请注册")
            invite = await self._get_valid_invitation(user_data.invite_token, user_data.email)

        if user_data.verification_code:
            await self.verify_email_code(email=user_data.email, code=user_data.verification_code, consume_only=True)

        tenant_id = invite.tenant_id if invite else (user_data.tenant_id or "default")
        role = invite.role if invite else "EMPLOYEE"
        level = invite.level if invite else ROLE_DEFAULT_LEVEL.get(role, 2)
        department = invite.department if invite and invite.department else user_data.department

        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=pwd_context.hash(user_data.password),
            department=department,
            tenant_id=tenant_id,
            role=role,
            level=level,
            is_active=True,
            email_verified=bool(user_data.verification_code),
            invited_by_id=invite.created_by_id if invite else None,
        )
        self.db.add(user)
        await self.db.flush()

        if invite is not None:
            invite.used_at = datetime.utcnow()

        if not user.email_verified:
            await self.create_verification_code(email=user.email, tenant_id=user.tenant_id, user_id=user.id)

        return user

    def create_tokens(self, user: User) -> dict:
        now = datetime.now(timezone.utc)
        access_expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
        refresh_expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)
        access_token = jwt.encode(
            {
                "sub": user.id,
                "tenant_id": user.tenant_id,
                "role": user.role,
                "username": getattr(user, "username", ""),
                "department": getattr(user, "department", "public"),
                "level": int(getattr(user, "level", 1) or 1),
                "type": "access",
                "exp": access_expire,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        refresh_token = jwt.encode(
            {"sub": user.id, "type": "refresh", "exp": refresh_expire},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
        }

    async def refresh(self, refresh_token: str) -> dict:
        try:
            payload = jwt.decode(refresh_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        except JWTError as exc:
            raise ValueError("无效的刷新令牌") from exc

        if payload.get("type") != "refresh":
            raise ValueError("令牌类型错误")

        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("令牌缺少用户标识")

        result = await self.db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在或已停用")
        return self.create_tokens(user)

    async def list_users(self, tenant_id: str):
        result = await self.db.execute(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at.desc()))
        return result.scalars().all()

    async def admin_update_user(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        user_id: str,
        username: str | None = None,
        role: str | None = None,
        department: str | None = None,
        level: int | None = None,
        is_active: bool | None = None,
        email_verified: bool | None = None,
    ) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")

        normalized_role = str(role or user.role).upper()
        if normalized_role not in ROLE_DEFAULT_LEVEL:
            raise ValueError("角色不合法")

        normalized_username = str(username or user.username).strip()
        if len(normalized_username) < 3:
            raise ValueError("用户名至少需要 3 个字符")

        if actor_id == user.id:
            if is_active is False:
                raise ValueError("不能停用当前管理员账号")
            if normalized_role != "ADMIN":
                raise ValueError("不能移除当前管理员的管理员角色")

        if normalized_username != user.username:
            duplicate = await self.db.execute(select(User).where(User.username == normalized_username, User.id != user.id))
            if duplicate.scalar_one_or_none() is not None:
                raise ValueError("用户名已存在")
            user.username = normalized_username

        user.role = normalized_role
        user.level = int(level if level is not None else ROLE_DEFAULT_LEVEL.get(normalized_role, user.level or 2))
        user.department = (department or "").strip() or None
        if is_active is not None:
            user.is_active = bool(is_active)
        if email_verified is not None:
            user.email_verified = bool(email_verified)
        await self.db.flush()
        return user

    async def admin_reset_password(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        user_id: str,
    ) -> tuple[User, str]:
        result = await self.db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        if actor_id == user.id:
            raise ValueError("不能重置当前管理员自己的密码")
        if not user.is_active:
            raise ValueError("停用用户不能直接重置密码")

        alphabet = string.ascii_letters + string.digits
        temporary_password = "".join(secrets.choice(alphabet) for _ in range(12))
        user.hashed_password = pwd_context.hash(temporary_password)
        await self.db.flush()
        return user, temporary_password

    async def admin_delete_user(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        user_id: str,
    ) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        if actor_id == user.id:
            raise ValueError("不能删除当前管理员自己")
        await self.db.delete(user)
        await self.db.flush()
        return user

    async def invite_user(self, *, current_user: User, payload) -> UserInvitation:
        self._validate_email_domain(payload.email)

        existing = await self.db.execute(
            select(UserInvitation).where(
                UserInvitation.email == payload.email,
                UserInvitation.tenant_id == current_user.tenant_id,
                UserInvitation.used_at.is_(None),
                UserInvitation.revoked_at.is_(None),
            )
        )
        invite = existing.scalar_one_or_none()
        if invite is None:
            invite = UserInvitation(
                tenant_id=current_user.tenant_id,
                email=payload.email,
                role=payload.role,
                department=payload.department,
                level=payload.level,
                created_by_id=current_user.id,
                expires_at=datetime.utcnow() + timedelta(hours=payload.expires_hours),
            )
            self.db.add(invite)
            await self.db.flush()
        else:
            invite.role = payload.role
            invite.department = payload.department
            invite.level = payload.level
            invite.expires_at = datetime.utcnow() + timedelta(hours=payload.expires_hours)
            invite.revoked_at = None

        await self.email_service.send_invitation(
            email=invite.email,
            token=invite.token,
            tenant_id=invite.tenant_id,
            role=invite.role,
        )
        return invite

    async def list_invitations(self, *, tenant_id: str, limit: int = 50, offset: int = 0):
        result = await self.db.execute(
            select(UserInvitation)
            .where(UserInvitation.tenant_id == tenant_id)
            .order_by(UserInvitation.created_at.desc())
            .limit(max(limit, 1))
            .offset(max(offset, 0))
        )
        return result.scalars().all()

    async def revoke_invitation(self, *, tenant_id: str, invitation_id: str) -> UserInvitation:
        result = await self.db.execute(
            select(UserInvitation).where(
                UserInvitation.id == invitation_id,
                UserInvitation.tenant_id == tenant_id,
            )
        )
        invite = result.scalar_one_or_none()
        if invite is None:
            raise ValueError("邀请不存在")
        if invite.used_at is not None:
            raise ValueError("邀请已被使用，无法撤销")
        invite.revoked_at = datetime.utcnow()
        invite.expires_at = datetime.utcnow()
        return invite

    async def resend_invitation(self, *, tenant_id: str, invitation_id: str, expires_hours: int = 72) -> UserInvitation:
        result = await self.db.execute(
            select(UserInvitation).where(
                UserInvitation.id == invitation_id,
                UserInvitation.tenant_id == tenant_id,
            )
        )
        invite = result.scalar_one_or_none()
        if invite is None:
            raise ValueError("邀请不存在")
        if invite.used_at is not None:
            raise ValueError("邀请已被使用，无法重发")

        invite.token = secrets.token_urlsafe(32)
        invite.revoked_at = None
        invite.expires_at = datetime.utcnow() + timedelta(hours=max(expires_hours, 1))
        await self.email_service.send_invitation(
            email=invite.email,
            token=invite.token,
            tenant_id=invite.tenant_id,
            role=invite.role,
        )
        return invite

    async def create_verification_code(self, *, email: str, tenant_id: str, user_id: str | None = None) -> str:
        code = f"{random.randint(0, 999999):06d}"
        record = EmailVerificationCode(
            user_id=user_id or "pending",
            tenant_id=tenant_id,
            email=email,
            code=code,
            purpose="verify_email",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        self.db.add(record)
        await self.db.flush()
        await self.email_service.send_verification_code(email=email, code=code, tenant_id=tenant_id)
        return code

    async def verify_email_code(self, *, email: str, code: str, consume_only: bool = False) -> User | None:
        result = await self.db.execute(
            select(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.code == code,
                EmailVerificationCode.purpose == "verify_email",
                EmailVerificationCode.consumed.is_(False),
            )
            .order_by(EmailVerificationCode.created_at.desc())
        )
        record = result.scalars().first()
        if record is None or record.expires_at < datetime.utcnow():
            raise ValueError("验证码无效或已过期")
        record.consumed = True

        if consume_only:
            return None

        user_result = await self.db.execute(select(User).where(User.email == email))
        user = user_result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        user.email_verified = True
        return user

    async def request_password_reset(self, *, email: str) -> str:
        result = await self.db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
        user = result.scalar_one_or_none()
        if user is None:
            return ""

        token = PasswordResetToken(
            user_id=user.id,
            tenant_id=user.tenant_id,
            expires_at=datetime.utcnow() + timedelta(hours=2),
        )
        self.db.add(token)
        await self.db.flush()
        await self.email_service.send_password_reset(email=user.email, token=token.token)
        return token.token

    async def reset_password(self, *, token: str, new_password: str) -> None:
        result = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.consumed.is_(False),
            )
        )
        record = result.scalar_one_or_none()
        if record is None or record.expires_at < datetime.utcnow():
            raise ValueError("重置令牌无效或已过期")

        user_result = await self.db.execute(select(User).where(User.id == record.user_id, User.is_active.is_(True)))
        user = user_result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")

        user.hashed_password = pwd_context.hash(new_password)
        record.consumed = True

    async def _get_valid_invitation(self, token: str, email: str) -> UserInvitation:
        result = await self.db.execute(
            select(UserInvitation).where(
                UserInvitation.token == token,
                UserInvitation.email == email,
                UserInvitation.used_at.is_(None),
                UserInvitation.revoked_at.is_(None),
            )
        )
        invite = result.scalar_one_or_none()
        if invite is None or invite.expires_at < datetime.utcnow():
            raise ValueError("邀请码无效或已过期")
        return invite

    def _validate_email_domain(self, email: str) -> None:
        allowlist = settings.auth_allowlist_domain_list
        if not allowlist:
            return
        if "@" not in email:
            raise ValueError("邮箱格式无效")
        domain = email.rsplit("@", 1)[1].lower()
        if domain in settings.auth_blocklist_domain_list:
            raise ValueError("该邮箱域名不允许注册")
        if domain not in allowlist:
            raise ValueError("该邮箱域名不在允许列表内")
