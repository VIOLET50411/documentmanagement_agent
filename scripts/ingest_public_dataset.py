#!/usr/bin/env python3
"""Upload public dataset PDFs into DocMind through the normal document API."""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import re
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"


def _safe_filename(title: str, suffix: str) -> str:
    cleaned = re.sub(r'[\\\\/:*?"<>|]+', "_", str(title or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    if not cleaned:
        cleaned = "document"
    return f"{cleaned}{suffix}"


async def _login(client: httpx.AsyncClient, username: str, password: str) -> None:
    response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})


async def _list_existing_titles(client: httpx.AsyncClient, page_size: int = 100) -> set[str]:
    page = 1
    titles: set[str] = set()
    while True:
        response = await client.get("/api/v1/documents/", params={"page": page, "size": page_size})
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("documents") or []
        for item in batch:
            title = str(item.get("title") or "").strip()
            if title:
                titles.add(title)
        total = int(payload.get("total") or 0)
        if len(titles) >= total or not batch:
            return titles
        page += 1


def _load_manifest(dataset_name: str) -> list[dict]:
    manifest_path = DATASETS_DIR / dataset_name / "sources.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _iter_document_entries(dataset_name: str) -> list[dict]:
    """Iterate all ingestible documents (PDF + HTML) from the dataset manifest."""
    supported_suffixes = {".pdf", ".html", ".htm"}
    entries = []
    for item in _load_manifest(dataset_name):
        saved_path = Path(str(item.get("saved_path") or ""))
        if not saved_path.exists():
            continue
        if saved_path.suffix.lower() not in supported_suffixes:
            continue
        title = str(item.get("title") or saved_path.stem).strip()
        entries.append({"title": title, "path": saved_path})
    return entries


def _filter_entries(entries: list[dict], include_patterns: list[str]) -> list[dict]:
    if not include_patterns:
        return entries
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in include_patterns]
    filtered: list[dict] = []
    for entry in entries:
        haystacks = [entry["title"], entry["path"].name, str(entry["path"])]
        if any(pattern.search(text) for pattern in compiled for text in haystacks):
            filtered.append(entry)
    return filtered


async def _wait_ready(client: httpx.AsyncClient, doc_id: str, timeout_seconds: int = 240) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        response = await client.get(f"/api/v1/documents/{doc_id}/status")
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status in {"ready", "partial_failed", "failed"}:
            return payload
        await asyncio.sleep(2)
    raise TimeoutError(f"document {doc_id} did not reach terminal status in {timeout_seconds}s")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest public dataset PDFs into DocMind")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--username", default="admin_demo")
    parser.add_argument("--password", default="Password123")
    parser.add_argument("--dataset", default="swu_public_docs")
    parser.add_argument("--department", default="public_corpus")
    parser.add_argument("--access-level", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="0 means all PDF entries")
    parser.add_argument(
        "--include-pattern",
        action="append",
        default=[],
        help="Regex filter applied to title and filename; repeatable",
    )
    args = parser.parse_args()

    entries = _iter_document_entries(args.dataset)
    entries = _filter_entries(entries, args.include_pattern)
    if args.limit > 0:
        entries = entries[: args.limit]

    async with httpx.AsyncClient(base_url=args.base_url, timeout=90.0) as client:
        await _login(client, args.username, args.password)
        existing_titles = await _list_existing_titles(client)

        uploaded: list[dict] = []
        skipped: list[str] = []
        failed: list[dict] = []

        for entry in entries:
            title = entry["title"]
            path: Path = entry["path"]
            upload_name = _safe_filename(title, path.suffix.lower())
            if upload_name in existing_titles:
                skipped.append(upload_name)
                continue

            content_type = mimetypes.guess_type(path.name)[0] or "application/pdf"
            with path.open("rb") as fh:
                response = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": (upload_name, fh, content_type)},
                    data={"department": args.department, "access_level": str(args.access_level)},
                )
            response.raise_for_status()
            payload = response.json()
            doc_id = payload["id"]
            terminal = await _wait_ready(client, doc_id)
            status = terminal.get("status")
            record = {"id": doc_id, "title": upload_name, "status": status}
            if status == "ready":
                uploaded.append(record)
                existing_titles.add(upload_name)
            else:
                failed.append({**record, "detail": terminal})

        print(
            json.dumps(
                {
                    "dataset": args.dataset,
                    "requested_count": len(entries),
                    "uploaded_count": len(uploaded),
                    "skipped_count": len(skipped),
                    "failed_count": len(failed),
                    "uploaded": uploaded[:20],
                    "failed": failed[:10],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
