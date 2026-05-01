from __future__ import annotations

import json

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


@pytest.mark.asyncio
async def test_push_health_summary_marks_multi_ready_when_subprovider_configured(monkeypatch):
    service = PushNotificationService(redis_client=object())
    monkeypatch.setattr(settings, 'push_notifications_enabled', True)
    monkeypatch.setattr(settings, 'push_notification_provider', 'multi')
    monkeypatch.setattr(settings, 'push_notification_fail_closed', False)
    monkeypatch.setattr(settings, 'push_fcm_server_key', '')
    monkeypatch.setattr(settings, 'push_fcm_access_token', 'access-token')
    monkeypatch.setattr(settings, 'push_fcm_project_id', 'docmind-7bbdd')
    monkeypatch.setattr(settings, 'push_fcm_service_account_file', '')
    monkeypatch.setattr(settings, 'push_apns_topic', '')
    monkeypatch.setattr(settings, 'push_apns_auth_token', '')
    monkeypatch.setattr(settings, 'push_wechat_access_token', '')
    monkeypatch.setattr(settings, 'push_wechat_template_id', '')

    payload = await service.get_health_summary(tenant_id='tenant-1')

    assert payload['ready'] is True
    assert payload['issues'] == []
    assert payload['active_providers'] == ['fcm']
    assert payload['active_provider_readiness']['fcm']['ready'] is True


@pytest.mark.asyncio
async def test_fcm_v1_dispatch_sends_each_device(monkeypatch):
    service = PushNotificationService(redis_client=object())
    payload = {
        'tenant_id': 'tenant-1',
        'user_id': 'user-1',
        'title': '测试消息',
        'body': '逐设备发送',
        'status': 'test',
    }
    devices = [
        {'platform': 'android', 'device_token': 'token-1'},
        {'platform': 'android', 'device_token': 'token-2'},
    ]
    calls = []

    monkeypatch.setattr(settings, 'push_fcm_server_key', '')
    monkeypatch.setattr(settings, 'push_fcm_access_token', 'access-token')
    monkeypatch.setattr(settings, 'push_fcm_project_id', 'docmind-7bbdd')
    monkeypatch.setattr(settings, 'push_fcm_service_account_file', '')

    class FakeResponse:
        status_code = 200
        text = '{"name":"projects/docmind/messages/1"}'

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, endpoint, json=None, headers=None):
            calls.append({'endpoint': endpoint, 'json': json, 'headers': headers})
            return FakeResponse()

    monkeypatch.setattr('app.services.push_notification_service.httpx.AsyncClient', FakeAsyncClient)

    result = await service._send_fcm_async(payload, devices)

    assert result['sent'] == 2
    assert result['failed'] == 0
    assert len(calls) == 2
    assert calls[0]['json']['message']['token'] == 'token-1'
    assert calls[1]['json']['message']['token'] == 'token-2'


@pytest.mark.asyncio
async def test_fcm_invalid_token_deactivates_device(monkeypatch):
    service = PushNotificationService(redis_client=object())
    payload = {
        'tenant_id': 'tenant-1',
        'user_id': 'user-1',
        'title': '测试消息',
        'body': '无效 token',
        'status': 'test',
    }
    devices = [{'platform': 'android', 'device_token': 'token-invalid-1'}]
    deactivated = {}

    monkeypatch.setattr(settings, 'push_fcm_server_key', '')
    monkeypatch.setattr(settings, 'push_fcm_access_token', 'access-token')
    monkeypatch.setattr(settings, 'push_fcm_project_id', 'docmind-7bbdd')
    monkeypatch.setattr(settings, 'push_fcm_service_account_file', '')
    monkeypatch.setattr(settings, 'push_auto_deactivate_invalid_tokens', True)

    async def fake_deactivate(self, runtime_payload, invalid_devices, *, provider, reason):
        deactivated['provider'] = provider
        deactivated['reason'] = reason
        deactivated['tokens'] = [item['device_token'] for item in invalid_devices]

    monkeypatch.setattr(PushNotificationService, '_deactivate_devices_async', fake_deactivate)

    class FakeErrorResponse:
        status_code = 400
        text = json.dumps(
            {
                'error': {
                    'status': 'INVALID_ARGUMENT',
                    'message': 'The registration token is not a valid FCM registration token',
                    'details': [{'errorCode': 'INVALID_ARGUMENT'}],
                }
            }
        )

        def json(self):
            return json.loads(self.text)

        def raise_for_status(self):
            import httpx

            request = httpx.Request('POST', 'https://fcm.googleapis.com/v1/projects/docmind/messages:send')
            raise httpx.HTTPStatusError('400 invalid token', request=request, response=self)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, endpoint, json=None, headers=None):
            return FakeErrorResponse()

    monkeypatch.setattr('app.services.push_notification_service.httpx.AsyncClient', FakeAsyncClient)

    result = await service._send_fcm_async(payload, devices)

    assert result['sent'] == 0
    assert result['failed'] == 1
    assert deactivated == {
        'provider': 'fcm',
        'reason': 'invalid_device_token',
        'tokens': ['token-invalid-1'],
    }


@pytest.mark.asyncio
async def test_push_device_summary_marks_current_token_status():
    from types import SimpleNamespace

    service = PushNotificationService(redis_client=object())

    async def fake_list_devices(*, tenant_id: str, user_id: str):
        assert tenant_id == 'tenant-1'
        assert user_id == 'user-1'
        return [
            SimpleNamespace(
                id='dev-1',
                tenant_id='tenant-1',
                user_id='user-1',
                platform='android',
                device_token='token-active',
                device_name='Pixel',
                app_version='1.0.0',
                is_active=True,
                created_at=None,
                updated_at=None,
                last_seen_at=None,
            ),
            SimpleNamespace(
                id='dev-2',
                tenant_id='tenant-1',
                user_id='user-1',
                platform='ios',
                device_token='token-inactive',
                device_name='iPhone',
                app_version='1.0.0',
                is_active=False,
                created_at=None,
                updated_at=None,
                last_seen_at=None,
            ),
        ]

    service.list_devices = fake_list_devices  # type: ignore[method-assign]

    summary = await service.summarize_devices(
        tenant_id='tenant-1',
        user_id='user-1',
        current_token='token-inactive',
    )

    assert summary['total'] == 2
    assert summary['active'] == 1
    assert summary['inactive'] == 1
    assert summary['current_token_status'] == 'matched_inactive'
    assert summary['current_device']['platform'] == 'ios'
