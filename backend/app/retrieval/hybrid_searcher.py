"""Hybrid searcher orchestration for local fallback retrieval."""

from __future__ import annotations

import asyncio
import ast
import json
import math
import re
import time

from elasticsearch import ApiError, TransportError
from sqlalchemy import and_, case, func, or_, select

from app.api.middleware.rbac import build_permission_filter
from app.config import settings
from app.dependencies import get_redis
from app.ingestion.embedder import DocumentEmbedder
from app.models.db.document import Document, DocumentChunk
from app.retrieval.es_client import ESClient
from app.retrieval.fusion import weighted_reciprocal_rank_fusion
from app.retrieval.graph_searcher import GraphSearcher
from app.retrieval.milvus_client import MilvusClient
from app.retrieval.reranker import Reranker
from app.services.retrieval_observability_service import RetrievalObservabilityService

try:
    from pymilvus.exceptions import MilvusException
except ImportError:  # pragma: no cover - optional dependency import fallback
    MilvusException = RuntimeError


class HybridSearcher:
    """Orchestrates multi-path retrieval: keyword + vector + graph."""

    GRAPH_HINTS = (
        "\u5173\u7cfb",
        "\u5173\u8054",
        "\u5f15\u7528",
        "\u4fee\u8ba2",
        "\u8d1f\u8d23",
        "\u8d1f\u8d23\u4eba",
        "\u5ba1\u6279\u4eba",
        "\u7531\u8c01",
        "\u8c01\u8d1f\u8d23",
        "\u5f52\u8c01",
        "\u4e0a\u7ea7",
        "\u4e0b\u7ea7",
        "\u5bf9\u6bd4",
        "\u6bd4\u8f83",
        "\u6d41\u7a0b",
        "\u8282\u70b9",
    )
    SYNTHETIC_TITLE_PATTERNS = (
        re.compile(r"^smoke(?:[_-][a-z0-9]+)?\.csv$"),
        re.compile(r"^loadtest(?:[_-][a-z0-9]+)?\.csv$"),
        re.compile(r"^perf[_-][a-z0-9]+\.csv$"),
        re.compile(r"^large\.csv$"),
        re.compile(r"^tmp[_a-z0-9-]*\.csv$"),
        re.compile(r"^push-test(?:-\d+)?\.csv$"),
        re.compile(r"^bad_upload\.txt$"),
        re.compile(r"^blocked_chat\.json$"),
    )
    KEYWORD_TIMEOUT_SECONDS = 2.0
    VECTOR_TIMEOUT_SECONDS = 0.35
    VECTOR_CONCURRENCY_LIMIT = 4
    VECTOR_ACQUIRE_TIMEOUT_SECONDS = 0.005
    _vector_semaphore = asyncio.Semaphore(VECTOR_CONCURRENCY_LIMIT)

    def __init__(self):
        self.embedder = DocumentEmbedder()
        self.reranker = Reranker()
        self.es_client = ESClient()
        self.milvus_client = MilvusClient(dim=self.embedder.dense_dim)

    async def search(self, query: str, user, top_k: int = 5, search_type: str = "hybrid", db=None) -> list[dict]:
        if db is None:
            return []

        filters = build_permission_filter(user)
        if search_type == "graph":
            results = await GraphSearcher().traverse(query=query, user=user, db=db, top_k=top_k)
            return self._filter_synthetic_results(results, query=query)[:top_k]

        query_terms = self._extract_terms(query)
        weighted_lists: list[list[dict]] = []
        weights: list[float] = []

        keyword_task = None
        vector_task = None
        if search_type in {"hybrid", "keyword"}:
            keyword_task = asyncio.create_task(
                self._run_with_timeout(
                    self._search_keyword_path(db, filters, query, query_terms, top_k=max(top_k * 4, 20)),
                    timeout_seconds=self.KEYWORD_TIMEOUT_SECONDS,
                )
            )
        if search_type == "vector" or (settings.hybrid_vector_enabled and search_type == "hybrid"):
            vector_task = asyncio.create_task(
                self._run_with_timeout(
                    self._search_vector_path(
                        db,
                        filters,
                        query,
                        top_k=max(top_k * 4, 20),
                        allow_fast_skip=False,
                    ),
                    timeout_seconds=self.VECTOR_TIMEOUT_SECONDS,
                )
            )

        if keyword_task is not None and vector_task is not None:
            keyword_results, vector_results = await asyncio.gather(keyword_task, vector_task)
            keyword_results = self._filter_synthetic_results(keyword_results, query=query)
            vector_results = self._filter_synthetic_results(vector_results, query=query)
            weighted_lists.append(keyword_results)
            weights.append(1.15 if self._is_keyword_heavy(query) else 1.0)
            weighted_lists.append(vector_results)
            weights.append(1.2 if not self._is_keyword_heavy(query) else 0.9)
        elif keyword_task is not None:
            keyword_results = await keyword_task
            keyword_results = self._filter_synthetic_results(keyword_results, query=query)
            weighted_lists.append(keyword_results)
            weights.append(1.15 if self._is_keyword_heavy(query) else 1.0)
        elif vector_task is not None:
            vector_results = await vector_task
            vector_results = self._filter_synthetic_results(vector_results, query=query)
            weighted_lists.append(vector_results)
            weights.append(1.2 if not self._is_keyword_heavy(query) else 0.9)

        if search_type == "hybrid" and self._should_include_graph(query):
            graph_started = time.perf_counter()
            graph_results = await GraphSearcher().traverse(query=query, user=user, db=db, top_k=max(top_k * 2, 8))
            await RetrievalObservabilityService(get_redis()).record(
                filters["tenant_id"],
                "graph",
                success=True,
                empty=not bool(graph_results),
                timeout=False,
                latency_ms=int((time.perf_counter() - graph_started) * 1000),
            )
            graph_results = self._filter_synthetic_results(graph_results, query=query)
            weighted_lists.append(graph_results)
            weights.append(1.3)

        fused = weighted_reciprocal_rank_fusion(weighted_lists, weights=weights)
        reranked = await self.reranker.rerank(
            query,
            fused,
            top_k=top_k,
            tenant_key=filters.get("tenant_id") or "default",
        )
        reranked = self._prefer_explicit_title_matches(reranked, query=query)
        return reranked[:top_k]

    async def _search_keyword_path(self, db, filters: dict, query: str, query_terms: list[str], top_k: int) -> list[dict]:
        started = time.perf_counter()
        explicit_titles = self._extract_explicit_titles(query)
        try:
            live_results = await self.es_client.search(query=query, filters=filters, top_k=top_k)
            await RetrievalObservabilityService(get_redis()).record(
                filters["tenant_id"],
                "es",
                success=True,
                empty=not bool(live_results),
                timeout=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            if live_results:
                return live_results
        except (ApiError, TransportError, OSError, RuntimeError, asyncio.TimeoutError) as exc:
            error_text = str(exc).lower()
            await RetrievalObservabilityService(get_redis()).record(
                filters["tenant_id"],
                "es",
                success=False,
                empty=False,
                timeout=("timeout" in error_text),
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(exc),
            )

        if not settings.vector_local_fallback_enabled:
            return []

        conditions = self._build_access_conditions(filters)
        content_conditions = [DocumentChunk.content.ilike(f"%{term}%") for term in query_terms]
        title_conditions = [Document.title.ilike(f"%{term}%") for term in query_terms]
        section_conditions = [DocumentChunk.section_title.ilike(f"%{term}%") for term in query_terms]
        exact_title_conditions = [Document.title.ilike(f"%{title}%") for title in explicit_titles]

        score_expr = (
            sum(
                case((DocumentChunk.content.ilike(f"%{term}%"), 2), else_=0)
                + case((Document.title.ilike(f"%{term}%"), 3), else_=0)
                + case((DocumentChunk.section_title.ilike(f"%{term}%"), 2), else_=0)
                for term in query_terms
            )
            if query_terms
            else case((DocumentChunk.content.ilike(f"%{query}%"), 1), else_=0)
        )
        if exact_title_conditions:
            score_expr = score_expr + sum(case((condition, 12), else_=0) for condition in exact_title_conditions)

        rows = await db.execute(
            select(DocumentChunk, Document, score_expr.label("score"))
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(and_(*conditions), or_(*(content_conditions + title_conditions + section_conditions + exact_title_conditions)))
            .order_by(score_expr.desc(), func.length(DocumentChunk.content).asc())
            .limit(top_k)
        )
        return [self._result_payload(chunk, document, float(score or 0), "keyword") for chunk, document, score in rows.all()]

    async def _search_vector_path(self, db, filters: dict, query: str, top_k: int, allow_fast_skip: bool = False) -> list[dict]:
        started = time.perf_counter()
        tenant_key = filters.get("tenant_id") or "default"
        explicit_titles = self._extract_explicit_titles(query)
        semaphore = self.__class__._vector_semaphore
        acquired = False
        query_embedding = self.embedder.local_embed_query(query) if allow_fast_skip else await self.embedder.aembed_query(query, tenant_key)
        try:
            try:
                await asyncio.wait_for(
                    semaphore.acquire(),
                    timeout=self.VECTOR_ACQUIRE_TIMEOUT_SECONDS if allow_fast_skip else self.VECTOR_TIMEOUT_SECONDS,
                )
                acquired = True
            except asyncio.TimeoutError:
                await RetrievalObservabilityService(get_redis()).record(
                    filters["tenant_id"],
                    "milvus",
                    success=False,
                    empty=True,
                    timeout=True,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error="vector_queue_saturated",
                )
                return []

            live_results = await self.milvus_client.search(query_embedding=query_embedding, filters=filters, top_k=top_k)
            await RetrievalObservabilityService(get_redis()).record(
                filters["tenant_id"],
                "milvus",
                success=True,
                empty=not bool(live_results),
                timeout=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            if live_results:
                return live_results
        except (MilvusException, OSError, RuntimeError, asyncio.TimeoutError) as exc:
            error_text = str(exc).lower()
            await RetrievalObservabilityService(get_redis()).record(
                filters["tenant_id"],
                "milvus",
                success=False,
                empty=False,
                timeout=("timeout" in error_text),
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(exc),
            )

            conditions = self._build_access_conditions(filters)
            rows = await db.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.doc_id)
                .where(and_(*conditions))
                .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
                .limit(max(top_k * 3, 60))
            )

            scored = []
            query_terms = self._extract_terms(query)
            for chunk, document in rows.all():
                metadata = self._safe_load_metadata(chunk.metadata_json)
                local_chunk_embedding = self.embedder.local_embed_query(chunk.content)
                chunk_embedding = {
                    "dense": metadata.get("dense_vector") or local_chunk_embedding.get("dense", []),
                    "sparse": metadata.get("sparse_vector") or local_chunk_embedding.get("sparse", {}),
                }
                score = self._dense_similarity(query_embedding["dense"], chunk_embedding["dense"])
                score += self._sparse_overlap(query_embedding["sparse"], chunk_embedding["sparse"])
                score += 0.15 if metadata.get("is_parent") else 0.0
                score += 0.1 if chunk.section_title and any(term in chunk.section_title for term in query_terms) else 0.0
                score += self._explicit_title_boost(document.title, explicit_titles)
                scored.append(self._result_payload(chunk, document, round(score, 6), "vector"))

            scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
            return [item for item in scored if item["score"] > 0][:top_k]
        finally:
            if acquired:
                semaphore.release()

    def _build_access_conditions(self, filters: dict):
        conditions = [DocumentChunk.tenant_id == filters["tenant_id"], Document.id == DocumentChunk.doc_id]
        if "access_level" in filters:
            conditions.append(Document.access_level <= filters["access_level"]["$lte"])
        if "department" in filters:
            conditions.append(Document.department.in_(filters["department"]["$in"]))
        return conditions

    def _result_payload(self, chunk, document, score: float, source_type: str) -> dict:
        return {
            "doc_id": chunk.doc_id,
            "chunk_id": chunk.id,
            "document_title": document.title,
            "snippet": chunk.content[:300],
            "page_number": chunk.page_number,
            "section_title": chunk.section_title,
            "score": score,
            "source_type": source_type,
            "department": document.department,
        }

    def _dense_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        try:
            import numpy as np

            a, b = np.asarray(left, dtype=np.float32), np.asarray(right, dtype=np.float32)
            norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))
        except ImportError:
            dot = sum(a * b for a, b in zip(left, right))
            left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
            right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
            return dot / (left_norm * right_norm)

    def _sparse_overlap(self, left: dict[str, float], right: dict[str, float]) -> float:
        overlap = 0.0
        for token, weight in left.items():
            if token in right:
                overlap += min(weight, right[token])
        return overlap

    def _safe_load_metadata(self, payload: str | None) -> dict:
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(payload)
                return parsed if isinstance(parsed, dict) else {}
            except (ValueError, SyntaxError):
                return {}

    def _should_include_graph(self, query: str) -> bool:
        normalized = str(query or "").strip()
        if any(token in normalized for token in self.GRAPH_HINTS):
            return True
        return bool(re.search(r"(谁.*负责|谁.*审批|由谁|归谁|上级|下级|关联关系)", normalized))

    def _is_keyword_heavy(self, query: str) -> bool:
        return bool(re.search(r"[A-Z]{2,}[-_]\d+|\d{4}", query)) or any(char in query for char in [":", "/", "_"])

    def _extract_terms(self, query: str) -> list[str]:
        cleaned = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query)
        terms = [term for term in cleaned if term]
        expanded = []
        for term in terms:
            expanded.append(term)
            if len(term) > 2 and re.search(r"[\u4e00-\u9fff]", term):
                expanded.extend(term[index : index + 2] for index in range(len(term) - 1))
        ordered = []
        seen = set()
        for term in expanded:
            if term not in seen:
                seen.add(term)
                ordered.append(term)
        return ordered or [query]

    def _extract_explicit_titles(self, query: str) -> list[str]:
        titles = []
        seen = set()
        for match in re.findall(r"《([^》]{2,80})》", query or ""):
            title = match.strip()
            if not title:
                continue
            for variant in self._title_variants(title):
                lower = variant.lower()
                if lower not in seen:
                    seen.add(lower)
                    titles.append(variant)
        return titles

    def _title_variants(self, title: str) -> list[str]:
        normalized = str(title or "").strip()
        if not normalized:
            return []
        variants = [normalized]
        stem = re.sub(r"\.(pdf|docx|doc|xlsx|xls|csv|txt)$", "", normalized, flags=re.IGNORECASE).strip()
        if stem and stem != normalized:
            variants.append(stem)
        return variants

    def _explicit_title_boost(self, document_title: str | None, explicit_titles: list[str]) -> float:
        normalized_title = str(document_title or "").strip().lower()
        if not normalized_title or not explicit_titles:
            return 0.0
        for title in explicit_titles:
            lowered = title.lower()
            if lowered and lowered in normalized_title:
                return 0.8
        return 0.0

    def _prefer_explicit_title_matches(self, results: list[dict], *, query: str) -> list[dict]:
        explicit_titles = self._extract_explicit_titles(query)
        if not explicit_titles:
            return results

        matched = []
        for item in results:
            normalized_title = str(item.get("document_title") or "").strip().lower()
            if not normalized_title:
                continue
            if any(title.lower() in normalized_title for title in explicit_titles):
                matched.append(item)
        return matched or results

    def _filter_synthetic_results(self, results: list[dict], *, query: str) -> list[dict]:
        filtered = [item for item in results if not self._should_exclude_synthetic_result(item, query=query)]
        return filtered

    def _should_exclude_synthetic_result(self, item: dict, *, query: str) -> bool:
        title = str(item.get("document_title") or "").strip()
        if not title:
            return False
        normalized_title = title.lower()
        normalized_query = str(query or "").strip().lower()
        if normalized_title and normalized_title in normalized_query:
            return False
        return any(pattern.fullmatch(normalized_title) for pattern in self.SYNTHETIC_TITLE_PATTERNS)

    async def _run_with_timeout(self, awaitable, timeout_seconds: float) -> list[dict]:
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return []
