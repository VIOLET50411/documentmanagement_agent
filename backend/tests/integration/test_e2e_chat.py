from __future__ import annotations

import json
import os

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("DOCMIND_INTEGRATION") != "1",
    reason="set DOCMIND_INTEGRATION=1 to run real integration tests",
)


@pytest.mark.asyncio
async def test_e2e_chat_stream_real_stack():
    base_url = os.getenv("DOCMIND_BASE_URL", "http://localhost:18000")
    username = os.getenv("DOCMIND_USERNAME", "admin_demo")
    password = os.getenv("DOCMIND_PASSWORD", "Password123")

    async with httpx.AsyncClient(base_url=base_url, timeout=45.0) as client:
        login = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
        login.raise_for_status()
        token = login.json()["access_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})

        got_status_event = False
        got_content_event = False
        got_done_event = False

        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"message": "请给我一句关于文档管理平台的简短说明。", "search_type": "hybrid"},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:].strip())
                status = payload.get("status")
                if status in {"thinking", "searching", "reading", "tool_call"}:
                    got_status_event = True
                if status == "streaming" and (payload.get("token") or payload.get("content")):
                    got_content_event = True
                if status == "done":
                    got_done_event = True
                    break

        assert got_status_event
        assert got_content_event
        assert got_done_event
