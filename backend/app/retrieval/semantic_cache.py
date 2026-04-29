"""Semantic cache backed by Redis values and Milvus vector lookup."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any

from app.config import settings
from app.ingestion.embedder import DocumentEmbedder
from app.observability.metrics import metrics_registry
from app.security.watermark import Watermarker

try:
    from pymilvus.exceptions import MilvusException
except ImportError:  # pragma: no cover - optional dependency import fallback
    MilvusException = RuntimeError


class SemanticCache:
    """Cache responses for repetitive and semantically similar queries."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.threshold = settings.semantic_cache_threshold
        self.top_k = settings.semantic_cache_top_k
        self.collection_name = settings.semantic_cache_collection
        self.watermarker = Watermarker()
        self.embedder = DocumentEmbedder()
        self._milvus_available = True
        self._degraded_until = 0.0

    async def get(self, query: str, user_id: str = None) -> dict | None:
        if not settings.semantic_cache_enabled or self.redis is None:
            return None

        key = self._build_key(query, user_id)
        payload = await self.redis.get(key)
        if payload:
            return self._decode_payload(payload, hit=True)

        vector_key = await self._search_vector_match(query, user_id)
        if not vector_key:
            metrics_registry.record_cache_miss()
            return None

        payload = await self.redis.get(vector_key)
        if not payload:
            metrics_registry.record_cache_miss()
            return None

        data = self._decode_payload(payload, hit=True)
        if data is not None:
            data["cache_key"] = vector_key
        return data

    async def put(
        self,
        query: str,
        answer: str,
        citations: list,
        ttl: int | None = None,
        user_id: str | None = None,
        *,
        degraded: bool = False,
        fallback_reason: str | None = None,
    ):
        if not settings.semantic_cache_enabled or self.redis is None:
            return

        cache_key = self._build_key(query, user_id)
        normalized_query = self._normalize_query(query)
        safe_answer = self.watermarker.strip(answer)
        payload = json.dumps(
            {
                "answer": safe_answer,
                "citations": citations,
                "normalized_query": normalized_query,
                "degraded": degraded,
                "fallback_reason": fallback_reason,
            },
            ensure_ascii=False,
        )
        expires_in = ttl or settings.semantic_cache_ttl_seconds
        await self.redis.set(cache_key, payload, ex=expires_in)

        doc_ids = {item.get("doc_id") for item in citations if item.get("doc_id")}
        for doc_id in doc_ids:
            await self.redis.sadd(f"semantic_cache:doc:{doc_id}", cache_key)
            await self.redis.expire(f"semantic_cache:doc:{doc_id}", expires_in)

        await self._upsert_vector_entry(cache_key, normalized_query, user_id, expires_in)

    async def invalidate_by_doc(self, doc_id: str):
        if self.redis is None:
            return None
        mapping_key = f"semantic_cache:doc:{doc_id}"
        cache_keys = await self.redis.smembers(mapping_key)
        if cache_keys:
            await self.redis.delete(*list(cache_keys))
            await self._delete_vector_entries(list(cache_keys))
        await self.redis.delete(mapping_key)
        return len(cache_keys)

    def _decode_payload(self, payload: str, hit: bool) -> dict | None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            metrics_registry.record_cache_miss()
            return None
        if "answer" in data:
            data["answer"] = self.watermarker.strip(data["answer"])
        if data.get("degraded"):
            metrics_registry.record_cache_miss()
            return None
        if hit:
            metrics_registry.record_cache_hit()
        return data

    async def _search_vector_match(self, query: str, user_id: str | None) -> str | None:
        if not self._vector_enabled():
            return None
        try:
            return await asyncio.to_thread(self._search_vector_match_sync, query, user_id)
        except (ImportError, ModuleNotFoundError, MilvusException, OSError, RuntimeError, TypeError, ValueError):
            self._milvus_available = False
            self._degraded_until = time.monotonic() + 30.0
            return None

    def _search_vector_match_sync(self, query: str, user_id: str | None) -> str | None:
        collection = self._get_collection()
        collection.load()
        embedding = self.embedder.embed_query(query, tenant_key=user_id or "anon")["dense"]
        expr = f'user_scope == "{self._user_scope(user_id)}"'
        result = collection.search(
            data=[self._normalize_dense(embedding)],
            anns_field="dense_vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=max(self.top_k, 1),
            expr=expr,
            output_fields=["cache_key", "normalized_query", "user_scope"],
        )
        for hit in result[0]:
            score = float(hit.distance)
            if score >= self.threshold:
                return str(hit.entity.get("cache_key"))
        return None

    async def _upsert_vector_entry(self, cache_key: str, normalized_query: str, user_id: str | None, ttl: int) -> None:
        if not self._vector_enabled():
            return
        try:
            await asyncio.to_thread(self._upsert_vector_entry_sync, cache_key, normalized_query, user_id, ttl)
        except (ImportError, ModuleNotFoundError, MilvusException, OSError, RuntimeError, TypeError, ValueError):
            self._milvus_available = False
            self._degraded_until = time.monotonic() + 30.0

    def _upsert_vector_entry_sync(self, cache_key: str, normalized_query: str, user_id: str | None, ttl: int) -> None:
        collection = self._get_collection()
        collection.delete(expr=f'cache_key == "{cache_key}"')
        dense = self.embedder.embed_query(normalized_query, tenant_key=user_id or "anon")["dense"]
        expires_at = int(time.time()) + int(ttl)
        rows = [
            [cache_key],
            [self._user_scope(user_id)],
            [normalized_query[:1024]],
            [expires_at],
            [self._normalize_dense(dense)],
        ]
        collection.insert(rows)
        collection.flush()

    async def _delete_vector_entries(self, cache_keys: list[str]) -> None:
        if not cache_keys or not self._vector_enabled():
            return
        try:
            await asyncio.to_thread(self._delete_vector_entries_sync, cache_keys)
        except (ImportError, ModuleNotFoundError, MilvusException, OSError, RuntimeError, TypeError, ValueError):
            self._milvus_available = False
            self._degraded_until = time.monotonic() + 30.0

    def _delete_vector_entries_sync(self, cache_keys: list[str]) -> None:
        collection = self._get_collection()
        escaped = ",".join(f'"{item}"' for item in cache_keys if item)
        if escaped:
            collection.delete(expr=f"cache_key in [{escaped}]")
            collection.flush()

    def _get_collection(self):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

        if not utility.has_collection(self.collection_name):
            fields = [
                FieldSchema(name="cache_key", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="user_scope", dtype=DataType.VARCHAR, max_length=128),
                FieldSchema(name="normalized_query", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="expires_at", dtype=DataType.INT64),
                FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=self.embedder.dense_dim),
            ]
            schema = CollectionSchema(fields=fields, description="DocMind semantic cache vectors")
            collection = Collection(self.collection_name, schema=schema)
            collection.create_index("dense_vector", {"index_type": "FLAT", "metric_type": "COSINE", "params": {}})
        else:
            collection = Collection(self.collection_name)
        return collection

    def _vector_enabled(self) -> bool:
        if not self._milvus_available and self._degraded_until > time.monotonic():
            return False
        return True

    def _normalize_dense(self, vector: list[float] | None) -> list[float]:
        raw = vector or []
        target_dim = self.embedder.dense_dim
        if len(raw) == target_dim:
            return [float(item) for item in raw]
        if len(raw) > target_dim:
            return [float(item) for item in raw[:target_dim]]
        return [float(item) for item in raw] + [0.0] * max(target_dim - len(raw), 0)

    def _user_scope(self, user_id: str | None) -> str:
        return user_id or "anon"

    def _build_key(self, query: str, user_id: str | None) -> str:
        normalized = self._normalize_query(query)
        raw = f"{self._user_scope(user_id)}::{normalized}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"semantic_cache:{digest}"

    def _normalize_query(self, query: str) -> str:
        return re.sub(r"\s+", " ", (query or "").strip().lower())
