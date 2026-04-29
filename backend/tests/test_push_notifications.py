from __future__ import annotations

import pytest

from app.config import settings
from app.services.push_notification_service import PushNotificationService


def test_push_notification_service_builds_document_status_payload(monkeypatch):
    captured: dict[str, dict] = {}

    def fake_load(self, *, tenant_id: str, user_id: str):
        assert tenant_id == 'tenant-1'
        assert user_id == 'user-1'
        return [{"platform": "android", "device_token": "token-1", "device_name": "Pixel", "app_version": "1.0.0"}]

    def fake_record(self, payload: dict):
        captured['record'] = payload

    def fake_dispatch(self, payload: dict):
        captured['dispatch'] = payload
        return {'sent': 1, 'failed': 0, 'provider': 'multi', 'status': 'ok', 'providers': {'fcm': 1}, 'results': []}

    monkeypatch.setattr(PushNotificationService, '_load_active_devices_sync', fake_load)
    monkeypatch.setattr(PushNotificationService, '_record_notification_sync', fake_record)
    monkeypatch.setattr(PushNotificationService, '_dispatch_sync', fake_dispatch)

    result = PushNotificationService(redis_client=object()).send_document_status_sync(
        tenant_id='tenant-1',
        user_id='user-1',
        document_id='doc-1',
        title='制度.pdf',
        status='ready',
    )

    assert result['sent'] == 1
    assert captured['record']['title'] == '文档处理状态更新'
    assert captured['record']['body'] == '文档《制度.pdf》当前状态：ready'
    assert captured['dispatch']['document_id'] == 'doc-1'


@pytest.mark.asyncio
async def test_push_multi_provider_routes_devices(monkeypatch):
    service = PushNotificationService(redis_client=object())
    payload = {
        'tenant_id': 'tenant-1',
        'user_id': 'user-1',
        'title': '测试消息',
        'body': '这是一次联调',
        'status': 'test',
    }
    devices = [
        {'platform': 'android', 'device_token': 'fcm-1'},
        {'platform': 'ios', 'device_token': 'apns-1'},
        {'platform': 'wechat', 'device_token': 'wechat-openid'},
        {'platform': 'unknown', 'device_token': 'log-1'},
    ]

    monkeypatch.setattr(settings, 'push_notification_provider', 'multi')

    async def fake_dispatch(self, provider: str, _payload: dict, subset: list[dict]):
        return [{'provider': provider, 'sent': len(subset), 'failed': 0, 'error': None, 'device_count': len(subset)}]

    monkeypatch.setattr(PushNotificationService, '_dispatch_single_provider_async', fake_dispatch)

    results = await service._dispatch_multi_async(payload, devices)

    providers = {item['provider']: item['sent'] for item in results}
    assert providers == {'fcm': 1, 'apns': 1, 'wechat': 1, 'log': 1}


def test_push_provider_not_configured_falls_back_to_log(monkeypatch):
    service = PushNotificationService(redis_client=object())
    captured = {}

    def fake_log(self, payload: dict, devices: list[dict], provider: str = 'log'):
        captured['provider'] = provider
        captured['payload'] = payload
        captured['devices'] = devices
        return {'provider': provider, 'sent': len(devices), 'failed': 0, 'error': None, 'device_count': len(devices)}

    monkeypatch.setattr(settings, 'push_notification_fail_closed', False)
    monkeypatch.setattr(PushNotificationService, '_send_log', fake_log)

    result = service._provider_not_configured('fcm', {'title': 'x', 'body': 'y'}, [{'platform': 'android', 'device_token': 'abc'}])

    assert result['provider'] == 'fcm_fallback_log'
    assert captured['provider'] == 'fcm_fallback_log'
    assert captured['payload']['title'] == 'x'
    assert captured['devices'][0]['device_token'] == 'abc'


def test_push_provider_not_configured_fail_closed(monkeypatch):
    service = PushNotificationService(redis_client=object())
    monkeypatch.setattr(settings, 'push_notification_fail_closed', True)

    result = service._provider_not_configured('apns', {'title': 'x'}, [{'platform': 'ios', 'device_token': 'abc'}])

    assert result['provider'] == 'apns'
    assert result['failed'] == 1


def test_fcm_is_configured_with_service_account(monkeypatch):
    monkeypatch.setattr(settings, 'push_fcm_server_key', '')
    monkeypatch.setattr(settings, 'push_fcm_access_token', '')
    monkeypatch.setattr(settings, 'push_fcm_project_id', 'docmind-7bbdd')
    monkeypatch.setattr(settings, 'push_fcm_service_account_file', '/run/secrets/docmind/firebase-service-account.json')

    assert PushNotificationService()._fcm_configured() is True
