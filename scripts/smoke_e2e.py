#!/usr/bin/env python3
"""DocMind non-LLM E2E smoke test: auth -> upload -> status -> search -> chat SSE."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time

import httpx


def _build_sample_csv() -> str:
    fd, path = tempfile.mkstemp(prefix="docmind_smoke_", suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write("policy,owner,amount\n")
        f.write("员工报销流程,财务部,5000\n")
        f.write("差旅审批规则,行政部,3000\n")
    return path


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
            response.raise_for_status()
            return response.json()["access_token"]
        except Exception as exc:  # pragma: no cover - network retry path
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"login failed after retries: {last_error}")


async def _wait_document_ready(client: httpx.AsyncClient, doc_id: str, timeout_seconds: int = 120) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = await client.get(f"/api/v1/documents/{doc_id}/status")
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status in {"ready", "partial_failed", "failed"}:
            return payload
        await asyncio.sleep(2)
    raise TimeoutError(f"document {doc_id} did not reach terminal state in {timeout_seconds}s")


async def _chat_first_event(client: httpx.AsyncClient) -> float:
    started = time.perf_counter()
    async with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "请根据员工报销流程给出一句摘要", "search_type": "hybrid"},
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                _ = json.loads(line[5:].strip())
                return (time.perf_counter() - started) * 1000
    raise RuntimeError("SSE stream returned no data event")


async def main() -> None:
    parser = argparse.ArgumentParser(description="DocMind E2E smoke test")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--username", default="admin_demo")
    parser.add_argument("--password", default="Password123")
    args = parser.parse_args()

    sample_path = _build_sample_csv()
    try:
        async with httpx.AsyncClient(base_url=args.base_url, timeout=45.0) as client:
            token = await _login(client, args.username, args.password)
            client.headers.update({"Authorization": f"Bearer {token}"})

            with open(sample_path, "rb") as f:
                upload = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("smoke.csv", f, "text/csv")},
                    data={"department": "Platform", "access_level": "2"},
                )
            upload.raise_for_status()
            doc_id = upload.json()["id"]

            status = await _wait_document_ready(client, doc_id)
            search = await client.get("/api/v1/search/", params={"q": "报销流程", "top_k": 5, "search_type": "hybrid"})
            search.raise_for_status()
            first_event_ms = await _chat_first_event(client)

            print(
                json.dumps(
                    {
                        "ok": True,
                        "doc_id": doc_id,
                        "document_status": status.get("status"),
                        "search_total": search.json().get("total"),
                        "chat_first_event_ms": round(first_event_ms, 2),
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        try:
            os.remove(sample_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
