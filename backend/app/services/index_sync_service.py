"""Services for syncing existing documents into retrieval infrastructure."""

from __future__ import annotations

import ast
import json

from elasticsearch import ApiError, ConnectionError as ESConnectionError, NotFoundError, TransportError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.graph_extractor import GraphExtractor
from app.models.db.document import Document, DocumentChunk
from app.retrieval.es_client import ESClient
from app.retrieval.milvus_client import MilvusClient

try:
    from pymilvus.exceptions import MilvusException
except ImportError:  # pragma: no cover - optional dependency import fallback
    MilvusException = RuntimeError


class IndexSyncService:
    """Backfill chunks into ES, Milvus, and Neo4j."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def reindex_tenant(self, tenant_id: str, limit: int | None = None) -> dict:
        query = (
            select(Document, DocumentChunk)
            .join(DocumentChunk, DocumentChunk.doc_id == Document.id)
            .where(Document.tenant_id == tenant_id, Document.status == "ready")
            .order_by(Document.updated_at.desc(), DocumentChunk.chunk_index.asc())
        )
        if limit:
            query = query.limit(limit)

        rows = (await self.db.execute(query)).all()
        chunks: list[dict] = []
        for document, chunk in rows:
            metadata = self._load_metadata(chunk.metadata_json)
            chunks.append(
                {
                    "id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "tenant_id": chunk.tenant_id,
                    "access_level": metadata.get("access_level", document.access_level),
                    "department": metadata.get("department", document.department),
                    "title": document.title,
                    "section_title": chunk.section_title,
                    "page_number": chunk.page_number,
                    "content": chunk.content,
                    "dense_vector": metadata.get("dense_vector", []),
                    "sparse_vector": metadata.get("sparse_vector", {}),
                    "keywords": metadata.get("keywords", []),
                    "doc_type": metadata.get("doc_type"),
                    "sensitivity_level": metadata.get("sensitivity_level"),
                }
            )

        es_count = milvus_count = graph_count = 0
        if chunks:
            try:
                es_count = ESClient().bulk_index(chunks)
            except (ApiError, TransportError, ESConnectionError, NotFoundError, OSError, RuntimeError, TypeError, ValueError):
                es_count = 0
            try:
                dim = len(chunks[0].get("dense_vector", [])) or 12
                milvus_count = MilvusClient(dim=dim).upsert_chunks(chunks)
            except (MilvusException, OSError, RuntimeError, TypeError, ValueError):
                milvus_count = 0
            try:
                triples = await GraphExtractor().extract_and_store(chunks)
                graph_count = len(triples)
            except (OSError, RuntimeError, TypeError, ValueError):
                graph_count = 0

        return {
            "tenant_id": tenant_id,
            "chunk_count": len(chunks),
            "es_indexed": es_count,
            "milvus_indexed": milvus_count,
            "graph_triples": graph_count,
        }

    def _load_metadata(self, payload: str | None) -> dict:
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
