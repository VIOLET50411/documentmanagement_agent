#!/usr/bin/env python3
"""Generate baseline performance report for non-LLM stage."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

from loadtest_baseline import run_chat_first_event_round, run_search_round


def _sample_upload_file() -> str:
    fd, path = tempfile.mkstemp(prefix="docmind_perf_", suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write("title,department,amount\n")
        for i in range(1, 8):
            f.write(f"报销条目{i},Platform,{i * 100}\n")
    return path


async def run_upload_round(base_url: str, token: str, total_requests: int, concurrency: int) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms: list[float] = []
    errors = 0
    error_types: dict[str, int] = {}
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0, headers=headers) as client:
        async def one_upload(i: int) -> None:
            nonlocal errors
            async with semaphore:
                path = _sample_upload_file()
                started = asyncio.get_running_loop().time()
                try:
                    with open(path, "rb") as f:
                        resp = await client.post(
                            "/api/v1/documents/upload",
                            files={"file": (f"perf_{i}.csv", f, "text/csv")},
                            data={"department": "Platform", "access_level": "2"},
                        )
                    if resp.status_code != 200:
                        errors += 1
                        key = f"http_{resp.status_code}"
                        error_types[key] = error_types.get(key, 0) + 1
                    else:
                        latencies_ms.append((asyncio.get_running_loop().time() - started) * 1000)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    key = type(exc).__name__
                    error_types[key] = error_types.get(key, 0) + 1
                finally:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

        await asyncio.gather(*(one_upload(i) for i in range(total_requests)))

    if not latencies_ms:
        return {"count": 0, "errors": errors, "avg_ms": None, "p95_ms": None, "max_ms": None, "error_types": error_types}
    values = sorted(latencies_ms)
    p95_idx = min(len(values) - 1, int(0.95 * (len(values) - 1)))
    return {
        "count": len(values),
        "errors": errors,
        "avg_ms": round(sum(values) / len(values), 2),
        "p95_ms": round(values[p95_idx], 2),
        "max_ms": round(values[-1], 2),
        "error_types": error_types,
    }


async def login_with_retry(base_url: str, username: str, password: str, max_attempts: int = 4) -> str:
    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=20.0) as client:
                resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
                resp.raise_for_status()
                return resp.json()["access_token"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(1.5)
    raise RuntimeError(f"login failed after retries: {last_error}")


def _build_markdown(payload: dict) -> str:
    summary = payload["summary"]
    checks = payload["checks"]
    lines = [
        "# DocMind Performance Baseline Report",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- base_url: {payload['base_url']}",
        "",
        "## Profile",
        "",
        f"- search: {summary['search_requests']} requests / concurrency {summary['search_concurrency']}",
        f"- chat: {summary['chat_requests']} requests / concurrency {summary['chat_concurrency']}",
        f"- upload: {summary['upload_requests']} requests / concurrency {summary['upload_concurrency']}",
        "",
        "## Metrics",
        "",
        "| Scenario | Count | Errors | Avg (ms) | P95 (ms) | Max (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("search", "chat_first_event", "upload"):
        m = checks[name]
        lines.append(f"| {name} | {m['count']} | {m['errors']} | {m['avg_ms']} | {m['p95_ms']} | {m['max_ms']} |")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="DocMind baseline performance report")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--username", default="admin_demo")
    parser.add_argument("--password", default="Password123")
    parser.add_argument("--search-requests", type=int, default=50)
    parser.add_argument("--search-concurrency", type=int, default=50)
    parser.add_argument("--chat-requests", type=int, default=20)
    parser.add_argument("--chat-concurrency", type=int, default=20)
    parser.add_argument("--upload-requests", type=int, default=10)
    parser.add_argument("--upload-concurrency", type=int, default=10)
    args = parser.parse_args()

    token = await login_with_retry(args.base_url, args.username, args.password)
    search_metric = await run_search_round(args.base_url, token, args.search_requests, args.search_concurrency, "员工手册")
    chat_metric = await run_chat_first_event_round(args.base_url, token, args.chat_requests, args.chat_concurrency, "请总结员工手册")
    upload_metric = await run_upload_round(args.base_url, token, args.upload_requests, args.upload_concurrency)

    payload = {
        "generated_at": datetime.now().isoformat(),
        "base_url": args.base_url,
        "summary": {
            "search_requests": args.search_requests,
            "search_concurrency": args.search_concurrency,
            "chat_requests": args.chat_requests,
            "chat_concurrency": args.chat_concurrency,
            "upload_requests": args.upload_requests,
            "upload_concurrency": args.upload_concurrency,
        },
        "checks": {
            "search": search_metric.summary(),
            "chat_first_event": chat_metric.summary(),
            "upload": upload_metric,
        },
    }

    report_dir = Path(__file__).resolve().parents[1] / "reports" / "performance"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"baseline_{ts}.json"
    md_path = report_dir / f"baseline_{ts}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown(payload), encoding="utf-8")

    print(str(json_path))
    print(str(md_path))
    print(json.dumps(payload["checks"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
