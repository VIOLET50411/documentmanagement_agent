"""Schemas for mobile OAuth2/OIDC with PKCE."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MobileAuthorizeRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=3, max_length=120)
    redirect_uri: str = Field(min_length=1, max_length=500)
    code_challenge: str = Field(min_length=16, max_length=256)
    code_challenge_method: str = Field(default="S256", pattern="^(S256|plain)$")
    scope: str = Field(default="openid profile email offline_access", max_length=255)
    state: str | None = Field(default=None, max_length=255)
    device_name: str | None = Field(default=None, max_length=120)


class MobileAuthorizeResponse(BaseModel):
    code: str
    expires_at: datetime
    redirect_uri: str
    state: str | None = None


class MobileTokenRequest(BaseModel):
    grant_type: str = Field(default="authorization_code", pattern="^(authorization_code|refresh_token)$")
    client_id: str = Field(min_length=3, max_length=120)
    code: str | None = Field(default=None, min_length=16, max_length=128)
    redirect_uri: str | None = Field(default=None, min_length=1, max_length=500)
    code_verifier: str | None = Field(default=None, min_length=16, max_length=256)
    refresh_token: str | None = Field(default=None, min_length=16, max_length=4096)


class MobileTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    id_token: str
    token_type: str = "bearer"
    expires_in: int
    scope: str


class MobileUserInfoResponse(BaseModel):
    sub: str
    username: str
    email: str
    email_verified: bool
    tenant_id: str
    role: str
    department: str | None = None
