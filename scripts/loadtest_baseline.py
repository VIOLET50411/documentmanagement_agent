#!/usr/bin/env python3
"""DocMind baseline load test (non-LLM stage)."""

from __future__ import annotations

import argparse
import asyncio
import io
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass
class Metric:
    latencies_ms: list[float]
    errors: int
    error_buckets: dict[str, int] | None = None

    def summary(self) -> dict:
        if not self.latencies_ms:
            return {
                "count": 0,
                "errors": self.errors,
                "avg_ms": None,
                "p95_ms": None,
                "max_ms": None,
                "error_buckets": self.error_buckets or {},
            }
        values = sorted(self.latencies_ms)
        p95_idx = min(len(values) - 1, int(0.95 * (len(values) - 1)))
        return {
            "count": len(values),
            "errors": self.errors,
            "avg_ms": round(statistics.mean(values), 2),
            "p95_ms": round(values[p95_idx], 2),
            "max_ms": round(values[-1], 2),
            "error_buckets": self.error_buckets or {},
        }


async def login(base_url: str, username: str, password: str) -> str:
    last_error: Exception | None = None
    limits = httpx.Limits(max_keepalive_connections=0, max_connections=1000)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(60.0), limits=limits) as client:
        for _ in range(8):
            try:
                health = await client.get("/health")
                if health.status_code != 200:
                    await asyncio.sleep(0.5)
                    continue
                response = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
                response.raise_for_status()
                return response.json()["access_token"]
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                await asyncio.sleep(1.0)
    assert last_error is not None
    raise last_error


async def run_search_round(base_url: str, token: str, total_requests: int, concurrency: int, query: str) -> Metric:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    error_buckets: dict[str, int] = {}
    headers = {"Authorization": f"Bearer {token}"}

    limits = httpx.Limits(max_keepalive_connections=0, max_connections=1000)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(120.0), headers=headers, limits=limits) as client:
        async def one_request() -> None:
            nonlocal errors
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get("/api/v1/search/", params={"q": query, "top_k": 5, "search_type": "hybrid"})
                    if response.status_code != 200:
                        errors += 1
                        key = f"status_{response.status_code}"
                        error_buckets[key] = error_buckets.get(key, 0) + 1
                    else:
                        latencies.append((time.perf_counter() - started) * 1000)
                except Exception as exc:
                    errors += 1
                    key = f"exception:{type(exc).__name__}"
                    error_buckets[key] = error_buckets.get(key, 0) + 1

        await asyncio.gather(*(one_request() for _ in range(total_requests)))
    return Metric(latencies_ms=latencies, errors=errors, error_buckets=error_buckets)


async def run_chat_first_event_round(base_url: str, token: str, total_requests: int, concurrency: int, message: str) -> Metric:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    error_buckets: dict[str, int] = {}
    headers = {"Authorization": f"Bearer {token}"}

    limits = httpx.Limits(max_keepalive_connections=0, max_connections=1000)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(120.0), headers=headers, limits=limits) as client:
        async def one_request(index: int) -> None:
            nonlocal errors
            async with semaphore:
                thread_id = f"loadtest-thread-{index}"
                payload = {"message": message, "thread_id": thread_id, "search_type": "hybrid"}
                started = time.perf_counter()
                try:
                    async with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
                        if response.status_code != 200:
                            errors += 1
                            key = f"status_{response.status_code}"
                            error_buckets[key] = error_buckets.get(key, 0) + 1
                            return
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                latencies.append((time.perf_counter() - started) * 1000)
                                break
                except Exception as exc:
                    errors += 1
                    key = f"exception:{type(exc).__name__}"
                    error_buckets[key] = error_buckets.get(key, 0) + 1

        await asyncio.gather(*(one_request(i) for i in range(total_requests)))
    return Metric(latencies_ms=latencies, errors=errors, error_buckets=error_buckets)


async def run_upload_round(base_url: str, token: str, total_requests: int, concurrency: int) -> Metric:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    error_buckets: dict[str, int] = {}
    headers = {"Authorization": f"Bearer {token}"}

    limits = httpx.Limits(max_keepalive_connections=0, max_connections=1000)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(120.0), headers=headers, limits=limits) as client:
        async def one_request(index: int) -> None:
            nonlocal errors
            async with semaphore:
                started = time.perf_counter()
                filename = f"loadtest_{index}.csv"
                payload = (
                    "employee,amount,department\n"
                    f"user_{index},{100 + index},finance\n"
                    f"user_{index}_2,{120 + index},ops\n"
                )
                files = {"file": (filename, io.BytesIO(payload.encode("utf-8")), "text/csv")}
                try:
                    response = await client.post("/api/v1/documents/upload", files=files, data={"access_level": "1"})
                    if response.status_code not in (200, 202):
                        errors += 1
                        key = f"status_{response.status_code}"
                        error_buckets[key] = error_buckets.get(key, 0) + 1
                    else:
                        latencies.append((time.perf_counter() - started) * 1000)
                except Exception as exc:
                    errors += 1
                    key = f"exception:{type(exc).__name__}"
                    error_buckets[key] = error_buckets.get(key, 0) + 1

        await asyncio.gather(*(one_request(i) for i in range(total_requests)))
    return Metric(latencies_ms=latencies, errors=errors, error_buckets=error_buckets)


async def main() -> None:
    parser = argparse.ArgumentParser(description="DocMind baseline load test")
    parser.add_argument("--base-url", default="http://localhost:18000", help="Backend base URL")
    parser.add_argument("--username", default="admin_demo", help="Login username")
    parser.add_argument("--password", default="Password123", help="Login password")
    parser.add_argument("--search-requests", type=int, default=100)
    parser.add_argument("--search-concurrency", type=int, default=50)
    parser.add_argument("--chat-requests", type=int, default=40)
    parser.add_argument("--chat-concurrency", type=int, default=20)
    parser.add_argument("--search-query", default="员工手册")
    parser.add_argument("--chat-message", default="请总结员工手册中的报销规则")
    parser.add_argument("--upload-requests", type=int, default=10)
    parser.add_argument("--upload-concurrency", type=int, default=10)
    args = parser.parse_args()

    token = await login(args.base_url, args.username, args.password)

    print("=== Search Round ===")
    search_metric = await run_search_round(
        args.base_url,
        token,
        total_requests=args.search_requests,
        concurrency=args.search_concurrency,
        query=args.search_query,
    )
    print(search_metric.summary())

    print("=== Chat First Event Round ===")
    chat_metric = await run_chat_first_event_round(
        args.base_url,
        token,
        total_requests=args.chat_requests,
        concurrency=args.chat_concurrency,
        message=args.chat_message,
    )
    print(chat_metric.summary())

    print("=== Upload Round ===")
    upload_metric = await run_upload_round(
        args.base_url,
        token,
        total_requests=args.upload_requests,
        concurrency=args.upload_concurrency,
    )
    print(upload_metric.summary())


if __name__ == "__main__":
    asyncio.run(main())

