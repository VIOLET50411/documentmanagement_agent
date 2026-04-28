from __future__ import annotations

from app.services.push_notification_service import PushNotificationService


def test_push_notification_service_builds_document_status_payload(monkeypatch):
    captured: dict[str, dict] = {}

    def fake_load(self, *, tenant_id: str, user_id: str):
        assert tenant_id == "tenant-1"
        assert user_id == "user-1"
        return [{"platform": "android", "device_token": "token-1", "device_name": "Pixel", "app_version": "1.0.0"}]

    def fake_record(self, payload: dict):
        captured["record"] = payload

    def fake_dispatch(self, payload: dict):
        captured["dispatch"] = payload

    monkeypatch.setattr(PushNotificationService, "_load_active_devices_sync", fake_load)
    monkeypatch.setattr(PushNotificationService, "_record_notification_sync", fake_record)
    monkeypatch.setattr(PushNotificationService, "_dispatch_sync", fake_dispatch)

    result = PushNotificationService(redis_client=object()).send_document_status_sync(
        tenant_id="tenant-1",
        user_id="user-1",
        document_id="doc-1",
        title="制度.pdf",
        status="ready",
    )

    assert result["sent"] == 1
    assert captured["record"]["title"] == "文档处理状态更新"
    assert captured["record"]["body"] == "文档《制度.pdf》当前状态：ready"
    assert captured["dispatch"]["document_id"] == "doc-1"
