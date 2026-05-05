"""Elasticsearch client with live search and indexing support."""

from __future__ import annotations

import asyncio

from elasticsearch import AsyncElasticsearch, Elasticsearch
from elasticsearch import ApiError, ConnectionError as ESConnectionError, NotFoundError, TransportError

from app.config import settings


class ESClient:
    """Elasticsearch BM25 search interface with best-effort live integration."""

    _index_ready: bool = False
    _index_lock = asyncio.Lock()

    def __init__(self):
        self.index = settings.es_index
        self.sync_client = Elasticsearch(hosts=[settings.es_url], request_timeout=5)
        self._async_client: AsyncElasticsearch | None = None

    async def search(self, query: str, filters: dict, top_k: int = 20) -> list[dict]:
        await self._ensure_index_async()
        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["document_title^3", "section_title^2", "snippet", "keywords^2"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "filter": self._build_es_filters(filters),
                }
            },
        }
        response = await self.async_client.search(index=self.index, body=body)
        hits = response.get("hits", {}).get("hits", [])
        return [
            {
                "doc_id": hit["_source"].get("doc_id"),
                "chunk_id": hit["_source"].get("chunk_id"),
                "document_title": hit["_source"].get("document_title"),
                "snippet": hit["_source"].get("snippet", ""),
                "page_number": hit["_source"].get("page_number"),
                "section_title": hit["_source"].get("section_title"),
                "score": float(hit.get("_score") or 0.0),
                "source_type": "es",
                "department": hit["_source"].get("department"),
            }
            for hit in hits
        ]

    def bulk_index(self, chunks: list[dict]) -> int:
        self._ensure_index_sync()
        operations = []
        for chunk in chunks:
            operations.append({"index": {"_index": self.index, "_id": chunk["id"]}})
            operations.append(
                {
                    "chunk_id": chunk["id"],
                    "doc_id": chunk.get("doc_id"),
                    "tenant_id": chunk.get("tenant_id"),
                    "access_level": chunk.get("access_level", 1),
                    "department": chunk.get("department"),
                    "document_title": chunk.get("title") or chunk.get("section_title"),
                    "section_title": chunk.get("section_title"),
                    "page_number": chunk.get("page_number"),
                    "snippet": chunk.get("content", "")[:2000],
                    "keywords": chunk.get("keywords", []),
                    "doc_type": chunk.get("doc_type"),
                    "sensitivity_level": chunk.get("sensitivity_level"),
                }
            )
        if not operations:
            return 0
        response = self.sync_client.bulk(operations=operations, refresh=True)
        return len(response.get("items", []))

    def delete_by_doc(self, doc_id: str) -> int:
        self._ensure_index_sync()
        response = self.sync_client.delete_by_query(
            index=self.index,
            query={"term": {"doc_id": doc_id}},
            refresh=True,
            ignore_unavailable=True,
        )
        return int(response.get("deleted", 0))

    def delete_by_tenant(self, tenant_id: str) -> int:
        self._ensure_index_sync()
        response = self.sync_client.delete_by_query(
            index=self.index,
            query={"term": {"tenant_id": tenant_id}},
            refresh=True,
            ignore_unavailable=True,
        )
        return int(response.get("deleted", 0))

    def health(self) -> dict:
        try:
            self._ensure_index_sync()
            count = self.sync_client.count(index=self.index).get("count", 0)
            return {"available": True, "index": self.index, "documents": int(count)}
        except (ApiError, TransportError, ESConnectionError, NotFoundError, OSError, RuntimeError) as exc:
            return {"available": False, "index": self.index, "documents": 0, "error": str(exc)}

    async def close(self) -> None:
        if self._async_client is not None:
            await self._async_client.close()
            self._async_client = None

    @property
    def async_client(self) -> AsyncElasticsearch:
        if self._async_client is None:
            self._async_client = AsyncElasticsearch(hosts=[settings.es_url], request_timeout=5)
        return self._async_client

    async def _ensure_index_async(self):
        if ESClient._index_ready:
            return
        async with ESClient._index_lock:
            if ESClient._index_ready:
                return
            exists = await self.async_client.indices.exists(index=self.index)
            if not exists:
                await self.async_client.indices.create(index=self.index, mappings=self._mapping())
            ESClient._index_ready = True

    def _ensure_index_sync(self):
        if ESClient._index_ready:
            return
        if not self.sync_client.indices.exists(index=self.index):
            self.sync_client.indices.create(index=self.index, mappings=self._mapping())
        ESClient._index_ready = True

    def _mapping(self):
        return {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "doc_id": {"type": "keyword"},
                "tenant_id": {"type": "keyword"},
                "access_level": {"type": "integer"},
                "department": {"type": "keyword"},
                "document_title": {"type": "text"},
                "section_title": {"type": "text"},
                "page_number": {"type": "integer"},
                "snippet": {"type": "text"},
                "keywords": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "sensitivity_level": {"type": "keyword"},
            }
        }

    def _build_es_filters(self, filters: dict) -> list[dict]:
        clauses = []
        if "tenant_id" in filters:
            clauses.append({"term": {"tenant_id": filters["tenant_id"]}})
        if "access_level" in filters:
            clauses.append({"range": {"access_level": {"lte": filters["access_level"]["$lte"]}}})
        if "department" in filters:
            clauses.append({"terms": {"department": filters["department"]["$in"]}})
        return clauses
