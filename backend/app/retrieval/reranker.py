"""Reranker with remote support and stronger local ranking heuristics."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.services.canary_router import in_canary_bucket
from app.services.llm_service import LLMService


class Reranker:
    """Rerank retrieved results using remote services or strong local heuristics."""

    DEPARTMENT_KEYWORDS = {
        "finance": ("\u8d22\u52a1", "\u62a5\u9500", "\u9884\u7b97", "\u5dee\u65c5", "expense", "reimburse", "invoice"),
        "hr": ("\u4eba\u4e8b", "\u5458\u5de5", "\u8bf7\u5047", "\u5e74\u5047", "\u8003\u52e4", "leave", "employee"),
        "legal": ("\u6cd5\u52a1", "\u5408\u89c4", "\u5408\u540c", "\u76d1\u7ba1", "legal", "compliance", "contract"),
        "procurement": ("\u91c7\u8d2d", "\u4f9b\u5e94\u5546", "\u62db\u6807", "vendor", "purchase", "supplier"),
    }

    def __init__(self):
        self.provider = (settings.reranker_provider or "local").lower()
        self.model = settings.reranker_model_name or "BAAI/bge-reranker-v2-m3"
        self.base_url = (settings.reranker_api_base_url or "").rstrip("/")
        self.api_key = settings.reranker_api_key or ""
        self.canary_percent = settings.reranker_canary_percent
        self.canary_seed = settings.reranker_canary_seed
        self.enabled = self.provider not in {"local", "fallback", "rule"} and (bool(self.base_url) or self.provider == "llm")
        self._remote_circuit_open_until = 0.0

    async def rerank(self, query: str, candidates: list, top_k: int = 5, tenant_key: str = "default") -> list:
        """Rerank candidates using deterministic business-aware scoring."""
        if self.enabled and in_canary_bucket(tenant_key, percent=self.canary_percent, seed=self.canary_seed):
            remote = await self._rerank_remote(query, candidates, top_k=top_k)
            if remote is not None:
                return remote

        return self._rerank_local(query, candidates, top_k=top_k)

    def _rerank_local(self, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        query_terms = self._tokenize(query)
        query_phrase = (query or "").strip().lower()
        inferred_departments = self._infer_query_departments(query_phrase)
        ranked = []

        for item in candidates:
            title = (item.get("document_title") or "").lower()
            section = (item.get("section_title") or "").lower()
            snippet = (item.get("snippet") or item.get("content") or "").lower()
            full_text = f"{title} {section} {snippet}".strip()

            overlap = sum(1 for term in query_terms if term and term in full_text)
            title_overlap = sum(1 for term in query_terms if term and term in title)
            section_overlap = sum(1 for term in query_terms if term and term in section)
            exact_phrase = 1 if query_phrase and query_phrase in full_text else 0
            same_department = self._department_boost(item.get("department"), inferred_departments)
            freshness = self._freshness_boost(item)
            base_score = float(item.get("score", 0.0))

            rerank_score = (
                base_score
                + overlap * 1.2
                + title_overlap * 2.0
                + section_overlap * 1.4
                + exact_phrase * 3.0
                + same_department
                + freshness
            )
            ranked.append({**item, "rerank_score": round(rerank_score, 6)})

        ranked.sort(
            key=lambda row: (
                row.get("rerank_score", 0.0),
                row.get("score", 0.0),
                row.get("document_title", ""),
            ),
            reverse=True,
        )
        return ranked[:top_k]

    async def _rerank_remote(self, query: str, candidates: list, top_k: int) -> list[dict] | None:
        if self._remote_circuit_open_until > time.monotonic():
            return None

        docs = [f"{item.get('document_title', '')}\\n{item.get('section_title', '')}\\n{item.get('snippet', '')}" for item in candidates]
        if not docs:
            return []

        if self.provider == "llm":
            return await self._rerank_by_llm(query, candidates, top_k, docs)

        try:
            timeout = httpx.Timeout(6.0, connect=1.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                endpoint = self.base_url + "/rerank"
                payload = {"model": self.model, "query": query, "documents": docs, "top_n": max(top_k, 1)}
                resp = await client.post(endpoint, json=payload, headers=self._headers())
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                results = data.get("results") or data.get("data") or []
                if not isinstance(results, list):
                    return None

                ranked: list[dict] = []
                for row in results:
                    if not isinstance(row, dict):
                        continue
                    idx = row.get("index")
                    score = row.get("relevance_score", row.get("score", 0.0))
                    if isinstance(idx, int) and 0 <= idx < len(candidates):
                        item = {
                            **candidates[idx],
                            "rerank_score": float(score or 0.0),
                            "source_type": candidates[idx].get("source_type", "reranker"),
                        }
                        ranked.append(item)

                if ranked:
                    ranked.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
                    return ranked[:top_k]
                return None
        except (httpx.HTTPError, TypeError, ValueError):
            self._remote_circuit_open_until = time.monotonic() + 30.0
            return None

    async def _rerank_by_llm(self, query: str, candidates: list[dict], top_k: int, docs: list[str]) -> list[dict] | None:
        prompt_lines = [f"query: {query}", "documents:"]
        for idx, doc in enumerate(docs[:40], start=1):
            prompt_lines.append(f"{idx}. {doc[:500]}")
        prompt_lines.append("\u8f93\u51fa JSON \u6570\u7ec4\uff0c\u4ec5\u5305\u542b\u6309\u76f8\u5173\u6027\u6392\u5e8f\u7684\u6587\u6863\u7f16\u53f7\uff0c\u4f8b\u5982 [3,1,2]\u3002")

        llm_text = await LLMService().generate(
            system_prompt="\u4f60\u662f\u68c0\u7d22\u91cd\u6392\u5668\uff0c\u53ea\u8f93\u51fa JSON \u6570\u7ec4\u3002",
            user_prompt="\\n".join(prompt_lines),
            temperature=0.0,
            max_tokens=200,
        )
        if not llm_text:
            self._remote_circuit_open_until = time.monotonic() + 30.0
            return None

        try:
            import json

            ranked_ids = json.loads(llm_text.strip())
            if not isinstance(ranked_ids, list):
                return None

            output = []
            for order, idx in enumerate(ranked_ids, start=1):
                if isinstance(idx, int) and 1 <= idx <= len(candidates):
                    row = {**candidates[idx - 1], "rerank_score": float(len(ranked_ids) - order + 1)}
                    output.append(row)
            if output:
                return output[:top_k]
            return None
        except (json.JSONDecodeError, TypeError, ValueError):
            self._remote_circuit_open_until = time.monotonic() + 30.0
            return None

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", (text or "").lower())

    def _infer_query_departments(self, query: str) -> set[str]:
        matches: set[str] = set()
        for department, keywords in self.DEPARTMENT_KEYWORDS.items():
            if any(keyword.lower() in query for keyword in keywords):
                matches.add(department)
        return matches

    def _department_boost(self, candidate_department: str | None, inferred_departments: set[str]) -> float:
        if not candidate_department or not inferred_departments:
            return 0.0
        return 1.0 if candidate_department.lower() in inferred_departments else 0.0

    def _freshness_boost(self, item: dict) -> float:
        raw_date = item.get("effective_date") or item.get("updated_at")
        if not raw_date:
            return 0.0
        try:
            normalized = str(raw_date).replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = max((datetime.now(timezone.utc) - dt).days, 0)
        except (TypeError, ValueError):
            return 0.0

        if age_days <= 30:
            return 0.6
        if age_days <= 180:
            return 0.3
        if age_days <= 365:
            return 0.1
        return 0.0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
