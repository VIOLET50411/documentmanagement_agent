#!/usr/bin/env python3
"""CI delivery gate for DocMind non-LLM stage."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings


async def wait_health(client: httpx.AsyncClient, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = await client.get("/health")
            if response.status_code == 200 and response.json().get("status") == "healthy":
                return
        except Exception:
            pass
        await asyncio.sleep(2)
    raise TimeoutError(f"health check did not pass within {timeout_seconds}s")


async def wait_remote_health(base_url: str, timeout_seconds: int = 120) -> None:
    if not base_url:
        return
    deadline = time.time() + timeout_seconds
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=15.0) as client:
        while time.time() < deadline:
            try:
                response = await client.get("/health")
                if response.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
    raise TimeoutError(f"remote health check did not pass within {timeout_seconds}s for {base_url}")


async def wait_evaluation_task(client: httpx.AsyncClient, headers: dict[str, str], task_id: str, timeout_seconds: int = 600) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = await client.get(f"/api/v1/admin/evaluation/tasks/{task_id}", headers=headers)
        response.raise_for_status()
        payload = response.json() or {}
        item = payload.get("item") or {}
        status = str(item.get("status") or "").lower()
        if status in {"completed", "failed", "killed"}:
            if status != "completed":
                raise RuntimeError(f"evaluation task failed: {json.dumps(payload, ensure_ascii=False)}")
            result = payload.get("result") or {}
            if isinstance(result, dict) and result.get("ok") is False:
                raise RuntimeError(f"evaluation task returned failure: {json.dumps(result, ensure_ascii=False)}")
            return result if isinstance(result, dict) else payload
        await asyncio.sleep(3)
    raise TimeoutError(f"evaluation task {task_id} did not finish within {timeout_seconds}s")


async def main() -> None:
    parser = argparse.ArgumentParser(description="DocMind CI gate")
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--username", default="admin_demo")
    parser.add_argument("--password", default="Password123")
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
        await wait_health(client)
        if settings.ci_gate_require_real_ragas:
            await wait_remote_health(settings.ragas_api_base_url, timeout_seconds=180)

        login = await client.post("/api/v1/auth/login", json={"username": args.username, "password": args.password})
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        eval_submit = await client.post(
            "/api/v1/admin/evaluation/run-async",
            params={"sample_limit": max(int(settings.ci_gate_eval_sample_limit), 1)},
            headers=headers,
        )
        eval_submit.raise_for_status()
        eval_task_id = (eval_submit.json() or {}).get("task_id")
        if not eval_task_id:
            raise RuntimeError(f"evaluation run did not return task_id: {eval_submit.text}")
        await wait_evaluation_task(client, headers, eval_task_id)
        eval_latest = await client.get("/api/v1/admin/evaluation/latest", headers=headers)
        eval_latest.raise_for_status()
        eval_payload = eval_latest.json() or {}
        eval_metrics = eval_payload.get("metrics") or {}
        eval_meta = eval_metrics.get("_meta") or {}

        readiness = await client.get("/api/v1/admin/system/readiness", headers=headers)
        readiness.raise_for_status()
        readiness_payload = readiness.json()

        integrity = await client.get("/api/v1/admin/system/retrieval-integrity", params={"sample_size": 8}, headers=headers)
        integrity.raise_for_status()
        integrity_payload = integrity.json()

        runtime_metrics = await client.get("/api/v1/admin/runtime/metrics", headers=headers)
        runtime_metrics.raise_for_status()
        runtime_metrics_payload = runtime_metrics.json()
        runtime_summary = runtime_metrics_payload.get("summary", {})

        security_policy = await client.get("/api/v1/admin/system/security-policy", headers=headers)
        security_policy.raise_for_status()
        security_policy_payload = security_policy.json()

        if not readiness_payload.get("ready"):
            raise RuntimeError(f"readiness gate failed: {json.dumps(readiness_payload, ensure_ascii=False)}")
        if not integrity_payload.get("healthy"):
            raise RuntimeError(f"retrieval integrity gate failed: {json.dumps(integrity_payload, ensure_ascii=False)}")
        if not security_policy_payload.get("compliant"):
            raise RuntimeError(f"security policy gate failed: {json.dumps(security_policy_payload, ensure_ascii=False)}")

        count = int(runtime_summary.get("count", 0) or 0)
        fallback_rate = float(runtime_summary.get("fallback_rate", 0.0) or 0.0)
        deny_rate = float(runtime_summary.get("deny_rate", 0.0) or 0.0)
        if count < settings.ci_gate_min_runtime_samples:
            raise RuntimeError(f"runtime metric sample too low: {json.dumps(runtime_summary, ensure_ascii=False)}")
        if fallback_rate > settings.ci_gate_max_fallback_rate:
            raise RuntimeError(f"runtime fallback_rate too high: {json.dumps(runtime_summary, ensure_ascii=False)}")
        if deny_rate > settings.ci_gate_max_deny_rate:
            raise RuntimeError(f"runtime deny_rate too high: {json.dumps(runtime_summary, ensure_ascii=False)}")
        if settings.ci_gate_require_real_ragas and not bool(eval_meta.get("real_mode")):
            raise RuntimeError(f"real ragas required but unavailable: {json.dumps(eval_metrics, ensure_ascii=False)}")
        faithfulness = float(eval_metrics.get("faithfulness", 0.0) or 0.0)
        answer_relevancy = float(eval_metrics.get("answer_relevancy", 0.0) or 0.0)
        context_precision = float(eval_metrics.get("context_precision", 0.0) or 0.0)
        context_recall = float(eval_metrics.get("context_recall", 0.0) or 0.0)
        dataset_size = int(eval_payload.get("dataset_size", 0) or 0)
        if dataset_size < settings.ci_gate_min_eval_dataset_size:
            raise RuntimeError(f"evaluation dataset_size too low: {dataset_size}")
        if faithfulness < settings.ci_gate_min_faithfulness:
            raise RuntimeError(f"faithfulness below gate: {faithfulness}")
        if answer_relevancy < settings.ci_gate_min_answer_relevancy:
            raise RuntimeError(f"answer_relevancy below gate: {answer_relevancy}")
        if context_precision < settings.ci_gate_min_context_precision:
            raise RuntimeError(f"context_precision below gate: {context_precision}")
        if context_recall < settings.ci_gate_min_context_recall:
            raise RuntimeError(f"context_recall below gate: {context_recall}")

        print(
            json.dumps(
                {
                    "ok": True,
                    "readiness_score": readiness_payload.get("score"),
                    "retrieval_integrity_score": integrity_payload.get("score"),
                    "runtime_samples": count,
                    "runtime_fallback_rate": fallback_rate,
                    "runtime_deny_rate": deny_rate,
                    "eval_meta": eval_meta,
                    "faithfulness": faithfulness,
                    "answer_relevancy": answer_relevancy,
                    "context_precision": context_precision,
                    "context_recall": context_recall,
                    "dataset_size": dataset_size,
                    "security_profile": security_policy_payload.get("profile"),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
