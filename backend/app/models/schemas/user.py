"""Pydantic schemas for user and auth APIs."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _normalize_email(value: str) -> str:
    if not EMAIL_RE.match(value):
        raise ValueError("邮箱格式不正确")
    return value.lower()


class UserLogin(BaseModel):
    username: str
    password: str


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str
    password: str = Field(min_length=8, max_length=128)
    department: str | None = None
    tenant_id: str | None = "default"
    invite_token: str | None = None
    verification_code: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class InviteUserRequest(BaseModel):
    email: str
    role: str = "EMPLOYEE"
    department: str | None = None
    level: int = Field(default=2, ge=1, le=9)
    expires_hours: int = Field(default=72, ge=1, le=168)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class VerifyEmailRequest(BaseModel):
    email: str
    code: str = Field(min_length=4, max_length=12)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class SendVerificationCodeRequest(BaseModel):
    email: str
    tenant_id: str | None = "default"
    username: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class RequestPasswordReset(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    role: str
    department: str | None
    tenant_id: str
    level: int | None = None
    email_verified: bool = False
    created_at: datetime


class InviteResponse(BaseModel):
    invitation_id: str
    email: str
    token: str
    expires_at: datetime


class InvitationRecord(BaseModel):
    invitation_id: str
    email: str
    role: str
    department: str | None
    level: int
    status: str
    created_by_id: str | None
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class GenericMessage(BaseModel):
    message: str
