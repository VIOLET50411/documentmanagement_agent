"""Evaluation pipeline fallback compatible with future Ragas integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.config import settings


class RagasRunner:
    """Run a deterministic fallback evaluation over a golden dataset."""

    async def evaluate(self, dataset_path: str | None = None, dataset: list[dict] | None = None) -> dict:
        rows = dataset or self._load_dataset(dataset_path)
        remote = await self._evaluate_remote(rows)
        if remote is not None:
            return remote
        if not rows:
            return {
                "faithfulness": 0.0,
                "answer_relevancy": 0.0,
                "context_precision": 0.0,
                "context_recall": 0.0,
                "sample_count": 0,
                "_meta": {"real_mode": False, "mode": "fallback", "reason": "empty_dataset"},
            }

        scores = {
            "faithfulness": [],
            "answer_relevancy": [],
            "context_precision": [],
            "context_recall": [],
        }

        for row in rows:
            answer = (row.get("answer") or row.get("response") or "").strip()
            contexts = row.get("contexts") or row.get("retrieved_contexts") or []
            context_text = " ".join(contexts).strip()
            question = (row.get("question") or row.get("user_input") or "").strip()

            faithfulness = self._overlap(answer, context_text)
            relevancy = self._overlap(answer, question + " " + context_text)
            precision = self._overlap(context_text, answer)
            recall = self._overlap(answer, context_text)

            scores["faithfulness"].append(faithfulness)
            scores["answer_relevancy"].append(relevancy)
            scores["context_precision"].append(precision)
            scores["context_recall"].append(recall)

        result = {key: round(sum(values) / len(values), 4) for key, values in scores.items()} | {
            "sample_count": len(rows),
            "_meta": {"real_mode": False, "mode": "fallback"},
        }
        return result

    def _load_dataset(self, dataset_path: str | None) -> list[dict]:
        if not dataset_path:
            return []
        path = Path(dataset_path)
        if not path.exists():
            return []
        if path.suffix.lower() == ".jsonl":
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return json.loads(path.read_text(encoding="utf-8"))

    def _overlap(self, left: str, right: str) -> float:
        left_tokens = {token for token in left.split() if token}
        right_tokens = {token for token in right.split() if token}
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens)

    async def _evaluate_remote(self, rows: list[dict]) -> dict[str, Any] | None:
        base_url = (settings.ragas_api_base_url or "").rstrip("/")
        if not base_url:
            return None
        try:
            timeout_seconds = max(float(settings.ragas_timeout_seconds), 30.0)
            async with httpx.AsyncClient(timeout=timeout_seconds + 30.0) as client:
                headers = {"Content-Type": "application/json"}
                if settings.ragas_api_key:
                    headers["Authorization"] = f"Bearer {settings.ragas_api_key}"
                resp = await client.post(base_url + "/evaluate", json={"dataset": rows}, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
            result = {
                "faithfulness": self._safe_float(payload.get("faithfulness"), 0.0),
                "answer_relevancy": self._safe_float(payload.get("answer_relevancy"), 0.0),
                "context_precision": self._safe_float(payload.get("context_precision"), 0.0),
                "context_recall": self._safe_float(payload.get("context_recall"), 0.0),
                "sample_count": self._safe_int(payload.get("sample_count"), len(rows)),
                "_meta": {
                    "real_mode": bool(payload.get("real_mode", True)),
                    "mode": str(payload.get("engine") or "ragas_api"),
                },
            }
            if settings.ragas_require_real_mode and not result["_meta"]["real_mode"]:
                raise RuntimeError(payload.get("error") or "ragas sidecar returned heuristic mode")
            return result
        except (httpx.HTTPError, json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError):
            if settings.ragas_require_real_mode:
                raise
            return None

    def _safe_float(self, value: Any, default: float) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default


if __name__ == "__main__":
    import asyncio

    runner = RagasRunner()
    results = asyncio.run(runner.evaluate())
    print("Evaluation Results:", results)
