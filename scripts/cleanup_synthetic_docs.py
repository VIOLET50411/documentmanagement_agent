#!/usr/bin/env python3
"""Delete synthetic/test documents from DocMind via the public API."""

from __future__ import annotations

import argparse
import asyncio
import json
import re

import httpx


SYNTHETIC_TITLE_PATTERNS = (
    re.compile(r"^smoke(?:[_-].*)?\.csv$", re.IGNORECASE),
    re.compile(r"^loadtest(?:[_-].*)?\.csv$", re.IGNORECASE),
    re.compile(r"^perf[_-].*\.csv$", re.IGNORECASE),
    re.compile(r"^large\.csv$", re.IGNORECASE),
    re.compile(r"^tmp.*\.csv$", re.IGNORECASE),
    re.compile(r"^push-test(?:-\d+)?\.csv$", re.IGNORECASE),
    re.compile(r"^bad_upload\.txt$", re.IGNORECASE),
    re.compile(r"^blocked_chat\.json$", re.IGNORECASE),
)


async def _login(client: httpx.AsyncClient, username: str, password: str) -> None:
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})


async def _list_all_documents(client: httpx.AsyncClient, page_size: int) -> list[dict]:
    page = 1
    documents: list[dict] = []
    while True:
        response = await client.get("/api/v1/documents/", params={"page": page, "size": page_size})
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("documents") or []
        documents.extend(batch)
        total = int(payload.get("total") or 0)
        if len(documents) >= total or not batch:
            return documents
        page += 1


def _is_synthetic_title(title: str) -> bool:
    normalized = str(title or "").strip()
    return any(pattern.fullmatch(normalized) for pattern in SYNTHETIC_TITLE_PATTERNS)


async def _delete_documents(client: httpx.AsyncClient, docs: list[dict]) -> tuple[list[str], list[dict]]:
    deleted: list[str] = []
    failed: list[dict] = []
    for doc in docs:
        response = await client.delete(f"/api/v1/documents/{doc['id']}")
        if response.status_code == 200:
            deleted.append(doc["id"])
            continue
        failed.append({"id": doc["id"], "title": doc.get("title"), "status_code": response.status_code, "body": response.text[:500]})
    return deleted, failed


async def main() -> None:
    parser = argparse.ArgumentParser(description="Clean synthetic/test documents from DocMind")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--username", default="admin_demo")
    parser.add_argument("--password", default="Password123")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--execute", action="store_true", help="Actually delete matched documents")
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=45.0) as client:
        await _login(client, args.username, args.password)
        all_docs = await _list_all_documents(client, page_size=max(args.page_size, 1))
        matched = [doc for doc in all_docs if _is_synthetic_title(doc.get("title") or "")]

        summary: dict[str, object] = {
            "total_documents": len(all_docs),
            "matched_count": len(matched),
            "matched_titles": [doc.get("title") for doc in matched[:20]],
            "execute": args.execute,
        }

        if args.execute and matched:
            deleted, failed = await _delete_documents(client, matched)
            summary["deleted_count"] = len(deleted)
            summary["failed"] = failed

        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
