"""
RBAC Middleware - Role-Based Access Control
Enforces role hierarchy and permission checks.
"""

from fastapi import Depends, HTTPException, status

from app.api.middleware.auth import get_current_user
from app.models.db.user import User

# Role hierarchy (higher number = more privileges)
ROLE_HIERARCHY = {
    "VIEWER": 1,
    "EMPLOYEE": 2,
    "MANAGER": 3,
    "ADMIN": 4,
}


def require_role(minimum_role: str):
    """
    FastAPI dependency factory: ensures user has at least the specified role.
    Usage: current_user = Depends(require_role("ADMIN"))
    """
    async def _check_role(current_user: User = Depends(get_current_user)):
        user_level = ROLE_HIERARCHY.get(current_user.role, 0)
        required_level = ROLE_HIERARCHY.get(minimum_role, 999)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {minimum_role}, Current: {current_user.role}",
            )
        return current_user
    return _check_role


def build_permission_filter(user: User) -> dict:
    """
    Build Milvus/ES filter expressions based on user permissions.
    This is the RBAC pre-filter applied BEFORE similarity search.
    """
    filters = {
        "tenant_id": user.tenant_id,
    }

    if user.role == "ADMIN":
        return filters

    filters["access_level"] = {"$lte": user.level or ROLE_HIERARCHY.get(user.role, 1)}
    if user.department:
        filters["department"] = {"$in": [user.department, "public"]}

    return filters
