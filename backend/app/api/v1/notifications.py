"""Push notification device registration APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import get_current_user
from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.db.user import User
from app.models.schemas.push_device import (
    PushDeviceHeartbeatRequest,
    PushDeviceRegisterRequest,
    PushDeviceResponse,
    PushNotificationTestRequest,
    WechatMiniappSubscribeBindRequest,
    WechatMiniappSubscribeBindResponse,
)
from app.services.push_notification_service import PushNotificationService
from app.services.security_audit_service import SecurityAuditService

router = APIRouter()


@router.get('/devices', response_model=list[PushDeviceResponse])
async def list_push_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await PushNotificationService(db, get_redis()).list_devices(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
    )


@router.get('/events')
async def list_push_events(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {
        'items': await PushNotificationService(db, get_redis()).list_recent_events(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            limit=max(limit, 1),
        ),
        'limit': max(limit, 1),
    }


@router.get('/devices/summary')
async def summarize_push_devices(
    current_token: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await PushNotificationService(db, get_redis()).summarize_devices(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        current_token=current_token,
    )


@router.post('/devices', response_model=PushDeviceResponse)
async def register_push_device(
    payload: PushDeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PushNotificationService(db, get_redis())
    device = await service.register_device(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        platform=payload.platform,
        device_token=payload.device_token,
        device_name=payload.device_name,
        app_version=payload.app_version,
    )
    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        'push_device_registered',
        'low',
        '已登记推送设备',
        user_id=current_user.id,
        target=payload.device_name or payload.platform,
        result='ok',
        metadata={'platform': payload.platform},
    )
    return device


@router.post('/wechat/subscribe-bind', response_model=WechatMiniappSubscribeBindResponse)
async def bind_wechat_miniapp_subscription(
    payload: WechatMiniappSubscribeBindRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = PushNotificationService(db, get_redis())
    openid = await service.resolve_wechat_openid(payload.js_code)
    device = await service.register_device(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        platform='miniapp',
        device_token=openid,
        device_name=payload.device_name,
        app_version=payload.app_version,
    )
    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        'wechat_miniapp_subscription_bound',
        'low',
        '已绑定微信小程序订阅消息设备',
        user_id=current_user.id,
        target=payload.device_name or 'wechat-miniapp',
        result='ok',
        metadata={
            'platform': 'miniapp',
            'subscription_result': payload.subscription_result,
        },
    )
    return WechatMiniappSubscribeBindResponse(
        success=True,
        platform=device.platform,
        device_token=device.device_token,
        device_name=device.device_name,
        app_version=device.app_version,
        subscription_result=payload.subscription_result,
        provider_ready=service._wechat_configured(),
        template_id_configured=bool(settings.push_wechat_template_id),
        message='微信订阅消息授权与设备绑定已完成，可直接发送测试通知。',
    )


@router.post('/devices/heartbeat')
async def heartbeat_push_device(
    payload: PushDeviceHeartbeatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await PushNotificationService(db, get_redis()).heartbeat_device(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        device_token=payload.device_token,
        app_version=payload.app_version,
    )
    if not updated:
        raise HTTPException(status_code=404, detail='设备不存在')
    return {'status': 'ok'}


@router.post('/test')
async def send_test_notification(
    payload: PushNotificationTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await PushNotificationService(db, get_redis()).send_test_notification(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        title=payload.title,
        body=payload.body,
    )
    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        'push_notification_test_sent',
        'low',
        '已发送推送测试消息',
        user_id=current_user.id,
        target=current_user.username,
        result='ok',
        metadata=result,
    )
    return result


@router.delete('/devices')
async def unregister_push_device(
    payload: PushDeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await PushNotificationService(db, get_redis()).unregister_device(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        device_token=payload.device_token,
    )
    if not removed:
        raise HTTPException(status_code=404, detail='设备不存在')
    await SecurityAuditService(get_redis(), db).log_event(
        current_user.tenant_id,
        'push_device_unregistered',
        'low',
        '已注销推送设备',
        user_id=current_user.id,
        target=payload.device_name or payload.platform,
        result='ok',
        metadata={'platform': payload.platform},
    )
    return {'status': 'deleted'}
