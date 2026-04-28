"""
JWT Authentication Middleware
Validates JWT tokens and extracts current user.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db, set_db_tenant

security = HTTPBearer()


@dataclass
class AuthenticatedUser:
    id: str
    tenant_id: str
    role: str
    username: str
    department: str
    level: int
    email: str = ""
    is_active: bool = True


def decode_token(token: str) -> dict:
    """Decode JWT token and return claims for non-HTTP auth flows (e.g. WebSocket)."""
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Extract and validate user from JWT token."""
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
            )
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing tenant ID",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if settings.auth_stateless_jwt_context:
        await set_db_tenant(db, tenant_id)
        return AuthenticatedUser(
            id=user_id,
            tenant_id=tenant_id,
            role=payload.get("role", "VIEWER"),
            username=payload.get("username", ""),
            department=payload.get("department", "public"),
            level=int(payload.get("level", 1) or 1),
        )

    # Fetch user from database
    from app.models.db.user import User
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Set tenant context for PostgreSQL RLS
    await set_db_tenant(db, user.tenant_id)

    return user
