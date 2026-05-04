"""Mobile OAuth2/OIDC service with PKCE support."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.auth import OAuthAuthorizationCode
from app.models.db.user import User
from app.services.auth_service import AuthService


class MobileOAuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.auth_service = AuthService(db)

    async def authorize(
        self,
        *,
        username: str,
        password: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        scope: str,
        state: str | None = None,
    ) -> OAuthAuthorizationCode:
        self._validate_client(client_id=client_id, redirect_uri=redirect_uri)
        user = await self.auth_service.authenticate(username, password)
        if user is None:
            raise ValueError("用户名或密码错误")

        record = OAuthAuthorizationCode(
            tenant_id=user.tenant_id,
            user_id=user.id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope or "openid profile email offline_access",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=max(settings.auth_mobile_authorization_code_expire_minutes, 1)),
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict:
        self._validate_client(client_id=client_id, redirect_uri=redirect_uri)
        result = await self.db.execute(
            select(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.code == code,
                OAuthAuthorizationCode.client_id == client_id,
                OAuthAuthorizationCode.redirect_uri == redirect_uri,
                OAuthAuthorizationCode.consumed.is_(False),
            )
        )
        record = result.scalar_one_or_none()
        if record is None or record.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
            raise ValueError("授权码无效或已过期")
        if not self._verify_pkce(record.code_challenge, record.code_challenge_method, code_verifier):
            raise ValueError("PKCE 校验失败")

        user_result = await self.db.execute(
            select(User).where(User.id == record.user_id, User.tenant_id == record.tenant_id, User.is_active.is_(True))
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在或已停用")

        record.consumed = True
        tokens = self.auth_service.create_tokens(user)
        tokens["id_token"] = self._create_id_token(user=user, client_id=client_id, scope=record.scope)
        tokens["scope"] = record.scope
        return tokens

    async def refresh_tokens(
        self,
        *,
        refresh_token: str,
        client_id: str,
    ) -> dict:
        self._validate_client_id(client_id)
        tokens = await self.auth_service.refresh(refresh_token)
        access_payload = jwt.decode(tokens["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = str(access_payload.get("sub") or "").strip()
        if not user_id:
            raise ValueError("刷新后的访问令牌缺少用户标识")

        user_result = await self.db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = user_result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在或已停用")

        tokens["id_token"] = self._create_id_token(
            user=user,
            client_id=client_id,
            scope="openid profile email offline_access",
        )
        tokens["scope"] = "openid profile email offline_access"
        return tokens

    async def userinfo(self, user_id: str) -> dict:
        result = await self.db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = result.scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        return {
            "sub": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": bool(user.email_verified),
            "tenant_id": user.tenant_id,
            "role": user.role,
            "department": user.department,
        }

    def discovery_document(self, issuer: str) -> dict:
        issuer = issuer.rstrip("/")
        mobile_base = f"{issuer}/api/v1/auth/mobile"
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{mobile_base}/authorize",
            "token_endpoint": f"{mobile_base}/token",
            "userinfo_endpoint": f"{mobile_base}/userinfo",
            "jwks_uri": f"{mobile_base}/jwks",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": [settings.jwt_algorithm],
            "scopes_supported": ["openid", "profile", "email", "offline_access"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256", "plain"],
        }

    def bootstrap_document(self, issuer: str) -> dict:
        issuer = issuer.rstrip("/")
        api_base = f"{issuer}/api/v1"
        ws_base = issuer.replace("https://", "wss://").replace("http://", "ws://")
        status_payload = self.status(issuer)
        return {
            "api_base": api_base,
            "ws_base": f"{ws_base}/api/v1/ws/chat",
            "auth": {
                "discovery": status_payload.get("discovery") or self.discovery_document(issuer),
                "miniapp": status_payload.get("miniapp"),
                "client_profiles": status_payload.get("client_profiles", []),
            },
            "endpoints": {
                "chat_message": f"{api_base}/chat/message",
                "chat_stream": f"{api_base}/chat/stream",
                "chat_history": f"{api_base}/chat/history",
                "documents": f"{api_base}/documents",
                "search": f"{api_base}/search",
                "push_devices": f"{api_base}/notifications/devices",
                "push_summary": f"{api_base}/notifications/devices/summary",
            },
        }

    def status(self, issuer: str | None = None) -> dict:
        enabled = bool(settings.auth_mobile_oauth_enabled)
        clients = list(settings.auth_mobile_oauth_client_list)
        redirects = list(settings.auth_mobile_oauth_redirect_uri_list)
        issues: list[str] = []
        if enabled and not clients:
            issues.append("missing_clients")
        if enabled and not redirects:
            issues.append("missing_redirect_uris")
        if enabled and settings.auth_mobile_authorization_code_expire_minutes <= 0:
            issues.append("invalid_authorization_code_ttl")
        payload = {
            "enabled": enabled,
            "ready": enabled and not issues,
            "issues": issues,
            "clients": clients,
            "redirect_uris": redirects,
            "authorization_code_expire_minutes": max(settings.auth_mobile_authorization_code_expire_minutes, 0),
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "pkce_methods_supported": ["S256", "plain"],
            "token_endpoint_auth_methods_supported": ["none"],
            "jwt_algorithm": settings.jwt_algorithm,
            "client_profiles": self._build_client_profiles(clients, redirects),
        }
        if issuer:
            payload["discovery"] = self.discovery_document(issuer)
            payload["miniapp"] = self._build_miniapp_status(issuer, clients, redirects, enabled, issues)
        return payload

    def jwks(self) -> dict:
        return {"keys": []}

    def _validate_client(self, *, client_id: str, redirect_uri: str) -> None:
        if not settings.auth_mobile_oauth_enabled:
            raise ValueError("移动 OAuth 未启用")
        self._validate_client_id(client_id)
        if redirect_uri not in settings.auth_mobile_oauth_redirect_uri_list:
            raise ValueError("redirect_uri 不在允许列表中")

    def _validate_client_id(self, client_id: str) -> None:
        if not settings.auth_mobile_oauth_enabled:
            raise ValueError("移动 OAuth 未启用")
        if client_id not in settings.auth_mobile_oauth_client_list:
            raise ValueError("client_id 不在允许列表中")

    def _verify_pkce(self, expected_challenge: str, method: str, verifier: str) -> bool:
        if method == "plain":
            return verifier == expected_challenge
        if method != "S256":
            return False
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
        return challenge == expected_challenge

    def _create_id_token(self, *, user: User, client_id: str, scope: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user.id,
            "aud": client_id,
            "iss": settings.app_name,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.jwt_access_token_expire_minutes)).timestamp()),
            "email": user.email,
            "email_verified": bool(user.email_verified),
            "preferred_username": user.username,
            "tenant_id": user.tenant_id,
            "role": user.role,
            "scope": scope,
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    def _build_client_profiles(self, clients: list[str], redirects: list[str]) -> list[dict]:
        profiles: list[dict] = []
        for client_id in clients:
            recommended_for = "mobile_app"
            if "miniapp" in client_id or "wechat" in client_id:
                recommended_for = "miniapp"
            elif "capacitor" in client_id:
                recommended_for = "capacitor_app"

            matched_redirects = [item for item in redirects if self._redirect_matches_client(item, client_id)]
            profiles.append(
                {
                    "client_id": client_id,
                    "recommended_for": recommended_for,
                    "redirect_uris": matched_redirects,
                }
            )
        return profiles

    def _build_miniapp_status(
        self,
        issuer: str,
        clients: list[str],
        redirects: list[str],
        enabled: bool,
        issues: list[str],
    ) -> dict:
        normalized_issuer = issuer.rstrip("/")
        ws_base = normalized_issuer.replace("https://", "wss://").replace("http://", "ws://")
        miniapp_clients = [item for item in clients if "miniapp" in item or "wechat" in item]
        miniapp_redirects = [item for item in redirects if "servicewechat.com" in item or "miniapp" in item]
        miniapp_issues: list[str] = []
        if enabled and not miniapp_clients:
            miniapp_issues.append("missing_miniapp_client")
        if enabled and not miniapp_redirects:
            miniapp_issues.append("missing_miniapp_redirect_uri")
        miniapp_issues.extend(issue for issue in issues if issue not in miniapp_issues)

        return {
            "ready": enabled and not miniapp_issues,
            "issues": miniapp_issues,
            "clients": miniapp_clients,
            "redirect_uris": miniapp_redirects,
            "recommended_api_base": f"{normalized_issuer}/api/v1",
            "recommended_ws_base": f"{ws_base}/api/v1/ws/chat",
            "subscribe_template_id": settings.push_wechat_template_id or "",
            "subscribe_page": settings.push_wechat_page or "pages/docs/index",
        }

    def _redirect_matches_client(self, redirect_uri: str, client_id: str) -> bool:
        normalized_redirect = redirect_uri.lower()
        normalized_client = client_id.lower()
        if "miniapp" in normalized_client or "wechat" in normalized_client:
            return "servicewechat.com" in normalized_redirect or "miniapp" in normalized_redirect
        if "capacitor" in normalized_client:
            return "://" in normalized_redirect
        return True
