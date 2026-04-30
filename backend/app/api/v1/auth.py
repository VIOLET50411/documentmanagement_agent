"""Authentication API: login, registration, invitations, verification, and profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import get_current_user
from app.api.middleware.rbac import require_role
from app.api.middleware.rate_limit import rate_limit_check
from app.dependencies import get_db, get_redis
from app.models.db.user import User
from app.models.schemas.user import (
    GenericMessage,
    InvitationRecord,
    InviteResponse,
    InviteUserRequest,
    RefreshTokenRequest,
    RequestPasswordReset,
    ResetPasswordRequest,
    SendVerificationCodeRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    VerifyEmailRequest,
)
from app.models.schemas.mobile_auth import (
    MobileAuthorizeRequest,
    MobileAuthorizeResponse,
    MobileTokenRequest,
    MobileTokenResponse,
    MobileUserInfoResponse,
)
from app.services.auth_service import AuthService
from app.services.mobile_oauth_service import MobileOAuthService
from app.services.security_audit_service import SecurityAuditService

router = APIRouter()


def _client_key(request: Request, fallback: str) -> str:
    return request.client.host if request.client else fallback


def _invitation_status(item) -> str:
    from datetime import datetime

    if item.revoked_at is not None:
        return "revoked"
    if item.used_at is not None:
        return "used"
    if item.expires_at < datetime.utcnow():
        return "expired"
    return "pending"


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit_check(None, f"login:{_client_key(request, credentials.username)}", limit=20, window=60)
    auth_service = AuthService(db)
    try:
        user = await auth_service.authenticate(credentials.username, credentials.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return auth_service.create_tokens(user)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit_check(None, f"register:{_client_key(request, user_data.email)}", limit=8, window=3600)
    auth_service = AuthService(db)
    try:
        return await auth_service.register(user_data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    auth_service = AuthService(db)
    try:
        return await auth_service.refresh(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if hasattr(current_user, "created_at"):
        return current_user
    user = await db.scalar(select(User).where(User.id == current_user.id, User.tenant_id == current_user.tenant_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


@router.post("/invite", response_model=InviteResponse)
async def invite_user(
    payload: InviteUserRequest,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    auth_service = AuthService(db)
    invitation = await auth_service.invite_user(current_user=current_user, payload=payload)
    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        "user_invited",
        "low",
        f"Invited {payload.email} with role {payload.role}",
        user_id=current_user.id,
        target=payload.email,
        result="ok",
        metadata={"email": payload.email, "role": payload.role},
    )
    return InviteResponse(
        invitation_id=invitation.id,
        email=invitation.email,
        token=invitation.token,
        expires_at=invitation.expires_at,
    )


@router.get("/invitations", response_model=list[InvitationRecord])
async def list_invitations(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    rows = await AuthService(db).list_invitations(tenant_id=current_user.tenant_id, limit=limit, offset=offset)
    return [
        InvitationRecord(
            invitation_id=item.id,
            email=item.email,
            role=item.role,
            department=item.department,
            level=item.level,
            status=_invitation_status(item),
            created_by_id=item.created_by_id,
            expires_at=item.expires_at,
            used_at=item.used_at,
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.post("/invite/{invitation_id}/resend", response_model=InviteResponse)
async def resend_invitation(
    invitation_id: str,
    expires_hours: int = 72,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    try:
        invitation = await AuthService(db).resend_invitation(
            tenant_id=current_user.tenant_id,
            invitation_id=invitation_id,
            expires_hours=expires_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        "invitation_resent",
        "low",
        f"Resent invitation to {invitation.email}",
        user_id=current_user.id,
        target=invitation.email,
        result="ok",
        metadata={"invitation_id": invitation.id, "email": invitation.email},
    )
    return InviteResponse(
        invitation_id=invitation.id,
        email=invitation.email,
        token=invitation.token,
        expires_at=invitation.expires_at,
    )


@router.post("/invite/{invitation_id}/revoke", response_model=GenericMessage)
async def revoke_invitation(
    invitation_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    try:
        invitation = await AuthService(db).revoke_invitation(
            tenant_id=current_user.tenant_id,
            invitation_id=invitation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        "invitation_revoked",
        "medium",
        f"Revoked invitation for {invitation.email}",
        user_id=current_user.id,
        target=invitation.email,
        result="ok",
        metadata={"invitation_id": invitation.id, "email": invitation.email},
    )
    return GenericMessage(message="邀请已撤销")


@router.post("/send-verification-code", response_model=GenericMessage)
async def send_verification_code(
    payload: SendVerificationCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await rate_limit_check(None, f"verify-code:{_client_key(request, payload.email)}", limit=5, window=600)
    auth_service = AuthService(db)
    await auth_service.create_verification_code(
        email=payload.email,
        tenant_id=payload.tenant_id or "default",
        user_id="pending",
    )
    return GenericMessage(message="验证码已发送，请检查邮箱输出目录或第三方邮件服务。")


@router.post("/verify-email", response_model=GenericMessage)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    auth_service = AuthService(db)
    try:
        await auth_service.verify_email_code(email=payload.email, code=payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GenericMessage(message="邮箱验证成功")


@router.post("/password-reset/request", response_model=GenericMessage)
async def request_password_reset(payload: RequestPasswordReset, db: AsyncSession = Depends(get_db)):
    await AuthService(db).request_password_reset(email=payload.email)
    return GenericMessage(message="如果邮箱存在，系统已发送密码重置说明。")


@router.post("/password-reset/confirm", response_model=GenericMessage)
async def confirm_password_reset(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    try:
        await AuthService(db).reset_password(token=payload.token, new_password=payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GenericMessage(message="密码已更新")


@router.get("/mobile/.well-known/openid-configuration")
async def mobile_openid_configuration(request: Request, db: AsyncSession = Depends(get_db)):
    issuer = str(request.base_url).rstrip("/")
    return MobileOAuthService(db).discovery_document(issuer)


@router.get("/mobile/jwks")
async def mobile_openid_jwks(db: AsyncSession = Depends(get_db)):
    return MobileOAuthService(db).jwks()


@router.post("/mobile/authorize", response_model=MobileAuthorizeResponse)
async def mobile_authorize(payload: MobileAuthorizeRequest, db: AsyncSession = Depends(get_db)):
    try:
        record = await MobileOAuthService(db).authorize(
            username=payload.username,
            password=payload.password,
            client_id=payload.client_id,
            redirect_uri=payload.redirect_uri,
            code_challenge=payload.code_challenge,
            code_challenge_method=payload.code_challenge_method,
            scope=payload.scope,
            state=payload.state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MobileAuthorizeResponse(
        code=record.code,
        expires_at=record.expires_at,
        redirect_uri=record.redirect_uri,
        state=payload.state,
    )


@router.post("/mobile/token", response_model=MobileTokenResponse)
async def mobile_token(payload: MobileTokenRequest, db: AsyncSession = Depends(get_db)):
    try:
        service = MobileOAuthService(db)
        if payload.grant_type == "refresh_token":
            if not payload.refresh_token:
                raise ValueError("refresh_token 不能为空")
            tokens = await service.refresh_tokens(
                refresh_token=payload.refresh_token,
                client_id=payload.client_id,
            )
        else:
            if not payload.code or not payload.redirect_uri or not payload.code_verifier:
                raise ValueError("authorization_code 模式缺少必要参数")
            tokens = await service.exchange_code(
                code=payload.code,
                client_id=payload.client_id,
                redirect_uri=payload.redirect_uri,
                code_verifier=payload.code_verifier,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return MobileTokenResponse(**tokens)


@router.get("/mobile/userinfo", response_model=MobileUserInfoResponse)
async def mobile_userinfo(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await MobileOAuthService(db).userinfo(current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
