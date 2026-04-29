"""Schemas for push device registration APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PushDeviceRegisterRequest(BaseModel):
    platform: str = Field(min_length=2, max_length=20)
    device_token: str = Field(min_length=8, max_length=4096)
    device_name: str | None = Field(default=None, max_length=120)
    app_version: str | None = Field(default=None, max_length=40)


class PushDeviceHeartbeatRequest(BaseModel):
    device_token: str = Field(min_length=8, max_length=4096)
    app_version: str | None = Field(default=None, max_length=40)


class PushNotificationTestRequest(BaseModel):
    title: str = Field(default="DocMind 推送测试", min_length=2, max_length=120)
    body: str = Field(default="移动端推送链路已联通。", min_length=2, max_length=500)


class PushDeviceResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    platform: str
    device_token: str
    device_name: str | None = None
    app_version: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime

    class Config:
        from_attributes = True
