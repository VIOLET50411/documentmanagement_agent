"""Milvus client with live vector search support."""

from __future__ import annotations

import asyncio
import math
import re
import time

from redis import Redis

from app.config import settings

try:
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
    from pymilvus.exceptions import MilvusException
except ImportError:  # pragma: no cover - optional dependency import fallback
    Collection = CollectionSchema = DataType = FieldSchema = None
    connections = utility = None
    MilvusException = RuntimeError


class MilvusClient:
    """Milvus vector database client with best-effort live integration."""

    def __init__(self, dim: int | None = None):
        self.collection_name = settings.milvus_collection
        self.dim = self._resolve_dim(dim)
        self._connect_attempts = 0
        self._degraded_until = 0.0
        self._operation_timeout = max(float(settings.milvus_operation_timeout_seconds), 0.5)
        self._degraded_retry_seconds = max(int(settings.milvus_degraded_retry_seconds), 5)
        self.available = self._connect()

    async def search(self, query_embedding: dict, filters: dict, top_k: int = 20) -> list[dict]:
        if not self._ensure_available():
            return []
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, query_embedding, filters, top_k),
                timeout=1.2,
            )
        except asyncio.TimeoutError:
            self.available = False
            self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
            return []
        except (MilvusException, OSError, RuntimeError):
            self.available = False
            self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
            if not self._reconnect():
                return []
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._search_sync, query_embedding, filters, top_k),
                    timeout=1.2,
                )
            except asyncio.TimeoutError:
                self.available = False
                self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
                return []
            except (MilvusException, OSError, RuntimeError):
                self.available = False
                self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
                return []

    def upsert_chunks(self, chunks: list[dict]) -> int:
        if not chunks or not self._ensure_available():
            return 0
        try:
            collection = self._get_collection()
            chunk_ids = [chunk["id"] for chunk in chunks]
            escaped = ",".join(f'"{item}"' for item in chunk_ids)
            collection.delete(expr=f'chunk_id in [{escaped}]')
            rows = [
                chunk_ids,
                [chunk.get("doc_id") or "" for chunk in chunks],
                [chunk.get("tenant_id") or "default" for chunk in chunks],
                [int(chunk.get("access_level", 1) or 1) for chunk in chunks],
                [chunk.get("department") or "" for chunk in chunks],
                [chunk.get("title") or chunk.get("section_title") or "" for chunk in chunks],
                [chunk.get("section_title") or "" for chunk in chunks],
                [int(chunk.get("page_number") or 0) for chunk in chunks],
                [chunk.get("content", "")[:2000] for chunk in chunks],
                [self._normalize_dense(chunk.get("dense_vector")) for chunk in chunks],
            ]
            collection.insert(rows)
            collection.flush(timeout=self._operation_timeout)
            collection.load(timeout=self._operation_timeout)
            self.available = True
            return len(chunks)
        except (MilvusException, OSError, RuntimeError):
            self.available = False
            self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
            if self._reconnect():
                try:
                    collection = self._get_collection()
                    collection.load(timeout=self._operation_timeout)
                    self.available = True
                except (MilvusException, OSError, RuntimeError):
                    self.available = False
            return 0

    def delete_by_doc(self, doc_id: str) -> int:
        if not self._ensure_available():
            return 0
        try:
            collection = self._get_collection()
            response = collection.delete(expr=f'doc_id == "{doc_id}"')
            collection.flush(timeout=self._operation_timeout)
            self._best_effort_compact(collection)
            return getattr(response, "delete_count", 0)
        except (MilvusException, OSError, RuntimeError):
            self.available = False
            self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
            return 0

    def delete_by_tenant(self, tenant_id: str) -> int:
        if not tenant_id or not self._ensure_available():
            return 0
        try:
            collection = self._get_collection()
            response = collection.delete(expr=f'tenant_id == "{tenant_id}"')
            collection.flush(timeout=self._operation_timeout)
            self._best_effort_compact(collection)
            return getattr(response, "delete_count", 0)
        except (MilvusException, OSError, RuntimeError):
            self.available = False
            self._degraded_until = time.monotonic() + float(self._degraded_retry_seconds)
            return 0

    def health(self) -> dict:
        if not self._ensure_available():
            return {"available": False, "collection": self.collection_name, "entities": 0, "status": "degraded"}
        try:
            collection = self._get_collection()
            collection.load(timeout=self._operation_timeout)
            live_entities = self._count_live_rows(collection)
            raw_entities = int(collection.num_entities)
            self.available = True
            return {
                "available": True,
                "collection": self.collection_name,
                "entities": live_entities,
                "raw_entities": raw_entities,
                "status": "online",
            }
        except (MilvusException, OSError, RuntimeError) as exc:
            self.available = False
            return {
                "available": False,
                "collection": self.collection_name,
                "entities": 0,
                "status": "degraded",
                "error": str(exc),
            }

    def _search_sync(self, query_embedding: dict, filters: dict, top_k: int = 20) -> list[dict]:
        collection = self._get_collection()
        collection.load(timeout=self._operation_timeout)
        params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
        expr = self._build_filter_expr(filters)
        search_result = collection.search(
            data=[self._normalize_dense(query_embedding.get("dense"))],
            anns_field="dense_vector",
            param=params,
            limit=top_k,
            expr=expr or None,
            output_fields=["chunk_id", "doc_id", "department", "document_title", "section_title", "page_number", "snippet"],
        )
        hits = []
        dense_scores: dict[str, float] = {}
        for item in search_result[0]:
            entity = item.entity
            payload = {
                "doc_id": self._entity_value(entity, "doc_id"),
                "chunk_id": self._entity_value(entity, "chunk_id"),
                "document_title": self._entity_value(entity, "document_title"),
                "snippet": self._entity_value(entity, "snippet", ""),
                "page_number": self._entity_value(entity, "page_number") or None,
                "section_title": self._entity_value(entity, "section_title"),
                "score": float(item.distance),
                "source_type": "milvus",
                "department": self._entity_value(entity, "department") or None,
            }
            hits.append(payload)
            if payload["chunk_id"]:
                dense_scores[payload["chunk_id"]] = payload["score"]

        reranked = self._lexical_rerank(
            collection=collection,
            expr=expr,
            dense_hits=hits,
            dense_scores=dense_scores,
            query_embedding=query_embedding,
            top_k=top_k,
        )
        return reranked[:top_k]

    def _connect(self) -> bool:
        if connections is None:
            return False
        try:
            connections.connect(alias="default", host=settings.milvus_host, port=settings.milvus_port)
            self._connect_attempts += 1
            return True
        except (MilvusException, OSError, RuntimeError):
            return False

    def _reconnect(self, retries: int = 2, delay_seconds: float = 0.4) -> bool:
        if connections is None:
            return False
        for _ in range(max(retries, 1)):
            try:
                connections.disconnect(alias="default")
            except (MilvusException, OSError, RuntimeError):
                pass
            if self._connect():
                self.available = True
                return True
            time.sleep(delay_seconds)
        self.available = False
        return False

    def _ensure_available(self) -> bool:
        if self._degraded_until > time.monotonic():
            return False
        if self.available:
            return True
        return self._reconnect()

    def _get_collection(self):
        if Collection is None or CollectionSchema is None or FieldSchema is None or utility is None or DataType is None:
            raise RuntimeError("pymilvus is not available")

        if not utility.has_collection(self.collection_name, timeout=self._operation_timeout):
            fields = [
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="access_level", dtype=DataType.INT64),
                FieldSchema(name="department", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="document_title", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
                FieldSchema(name="page_number", dtype=DataType.INT64),
                FieldSchema(name="snippet", dtype=DataType.VARCHAR, max_length=2048),
                FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
            ]
            schema = CollectionSchema(fields=fields, description="DocMind dense vector chunks")
            collection = Collection(self.collection_name, schema=schema)
            collection.create_index("dense_vector", {"index_type": "FLAT", "metric_type": "COSINE", "params": {}})
        else:
            collection = Collection(self.collection_name)
            existing_dim = self._extract_collection_dim(collection)
            if existing_dim and existing_dim != self.dim:
                self.dim = existing_dim
        return collection

    def _build_filter_expr(self, filters: dict) -> str:
        parts = []
        if "tenant_id" in filters:
            parts.append(f'tenant_id == "{filters["tenant_id"]}"')
        if "access_level" in filters:
            parts.append(f'access_level <= {filters["access_level"]["$lte"]}')
        if "department" in filters:
            departments = ",".join(f'"{item}"' for item in filters["department"]["$in"])
            parts.append(f"department in [{departments}]")
        return " and ".join(parts) if parts else ""

    def _normalize_dense(self, vector: list[float] | None) -> list[float]:
        raw = vector or []
        if len(raw) == self.dim:
            return [float(item) for item in raw]
        if len(raw) > self.dim:
            return [float(item) for item in raw[: self.dim]]
        if len(raw) < self.dim:
            return [float(item) for item in raw] + [0.0] * (self.dim - len(raw))
        return [0.0] * self.dim

    def _extract_collection_dim(self, collection) -> int | None:
        try:
            for field in collection.schema.fields:
                if field.name == "dense_vector":
                    parsed = int(field.params.get("dim", 0))
                    return parsed if parsed > 0 else None
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        return None

    def _resolve_dim(self, provided_dim: int | None) -> int:
        if provided_dim and provided_dim > 0:
            return provided_dim
        try:
            client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1)
            value = client.get("embedding:detected_dim")
            client.close()
            if value is not None:
                parsed = int(value)
                if parsed > 0:
                    return parsed
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return 64

    def _count_live_rows(self, collection) -> int:
        iterator_factory = getattr(collection, "query_iterator", None)
        if iterator_factory is None:
            return int(collection.num_entities)

        total = 0
        iterator = None
        try:
            iterator = iterator_factory(
                batch_size=1000,
                limit=-1,
                expr='chunk_id != ""',
                output_fields=["chunk_id"],
                timeout=self._operation_timeout,
            )
            while True:
                batch = iterator.next()
                if not batch:
                    break
                total += len(batch)
            return total
        except (MilvusException, OSError, RuntimeError, AttributeError, TypeError, ValueError):
            return int(collection.num_entities)
        finally:
            if iterator is not None:
                close = getattr(iterator, "close", None)
                if callable(close):
                    try:
                        close()
                    except (MilvusException, OSError, RuntimeError, AttributeError, TypeError, ValueError):
                        pass

    def _best_effort_compact(self, collection) -> None:
        compact = getattr(collection, "compact", None)
        if not callable(compact):
            return
        try:
            compact()
        except (MilvusException, OSError, RuntimeError, AttributeError, TypeError, ValueError):
            return

    def _entity_value(self, entity, key: str, default=None):
        try:
            if hasattr(entity, "get"):
                value = entity.get(key)
                return default if value is None else value
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        try:
            value = entity[key]
            return default if value is None else value
        except (KeyError, TypeError, AttributeError):
            return default

    def _lexical_rerank(
        self,
        *,
        collection,
        expr: str,
        dense_hits: list[dict],
        dense_scores: dict[str, float],
        query_embedding: dict,
        top_k: int,
    ) -> list[dict]:
        tokens = [token for token in (query_embedding.get("sparse") or {}).keys() if token]
        if not tokens:
            return dense_hits

        candidates: list[dict] = []
        try:
            query_expr = expr or 'chunk_id != ""'
            candidates = collection.query(
                expr=query_expr,
                output_fields=["chunk_id", "doc_id", "department", "document_title", "section_title", "page_number", "snippet"],
                limit=max(top_k * 20, 200),
            )
        except (MilvusException, OSError, RuntimeError, AttributeError, TypeError, ValueError):
            return dense_hits

        merged: dict[str, dict] = {item.get("chunk_id"): item for item in dense_hits if item.get("chunk_id")}
        for row in candidates:
            chunk_id = row.get("chunk_id")
            if not chunk_id:
                continue
            lexical_score = self._lexical_score(tokens, row)
            if lexical_score <= 0:
                continue
            dense_score = dense_scores.get(chunk_id, 0.0)
            score = round(dense_score * 0.7 + lexical_score * 0.3, 6)
            payload = {
                "doc_id": row.get("doc_id"),
                "chunk_id": chunk_id,
                "document_title": row.get("document_title"),
                "snippet": row.get("snippet") or "",
                "page_number": row.get("page_number") or None,
                "section_title": row.get("section_title"),
                "score": score,
                "source_type": "milvus",
                "department": row.get("department") or None,
            }
            existing = merged.get(chunk_id)
            if existing is None or payload["score"] > existing.get("score", 0.0):
                merged[chunk_id] = payload

        items = list(merged.values())
        items.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        return items

    def _lexical_score(self, tokens: list[str], row: dict) -> float:
        title = str(row.get("document_title") or "")
        section = str(row.get("section_title") or "")
        snippet = str(row.get("snippet") or "")
        title_terms = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", title.lower()))
        section_terms = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", section.lower()))
        snippet_terms = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", snippet.lower()))
        score = 0.0
        for token in tokens:
            lowered = token.lower()
            if lowered in title_terms:
                score += 1.2
            if lowered in section_terms:
                score += 1.0
            if lowered in snippet_terms:
                score += 0.8
        norm = math.sqrt(len(tokens)) or 1.0
        return score / norm
