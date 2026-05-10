"""Services for syncing existing documents into retrieval infrastructure."""

from __future__ import annotations

import ast
import asyncio
import json

from elasticsearch import ApiError, ConnectionError as ESConnectionError, NotFoundError, TransportError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion.embedder import DocumentEmbedder
from app.ingestion.graph_extractor import GraphExtractor
from app.models.db.document import Document, DocumentChunk
from app.retrieval.es_client import ESClient
from app.retrieval.milvus_client import MilvusClient
from app.retrieval.neo4j_client import Neo4jClient

try:
    from pymilvus.exceptions import MilvusException
except ImportError:  # pragma: no cover - optional dependency import fallback
    MilvusException = RuntimeError


class IndexSyncService:
    """Backfill chunks into ES, Milvus, and Neo4j."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def audit_tenant_consistency(self, tenant_id: str, limit: int = 10, minio_client=None) -> dict:
        doc_rows = (
            await self.db.execute(
                select(Document)
                .where(Document.tenant_id == tenant_id)
                .order_by(Document.updated_at.desc())
                .limit(max(limit, 1) * 5)
            )
        ).scalars().all()

        docs = list(doc_rows)
        chunks = (
            await self.db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.tenant_id == tenant_id)
                .order_by(DocumentChunk.created_at.desc())
            )
        ).scalars().all()
        chunks_by_doc: dict[str, list[DocumentChunk]] = {}
        for chunk in chunks:
            chunks_by_doc.setdefault(chunk.doc_id, []).append(chunk)

        ready_docs = [doc for doc in docs if doc.status == "ready"]
        ready_doc_ids = {doc.id for doc in ready_docs}
        ready_chunk_count = sum(len(chunks_by_doc.get(doc_id, [])) for doc_id in ready_doc_ids)
        sampled_ready_docs = [doc for doc in ready_docs if chunks_by_doc.get(doc.id)][: max(limit, 1)]

        minio_missing = []
        docs_without_chunks = []
        for document in docs[: max(limit, 1) * 3]:
            if not chunks_by_doc.get(document.id):
                docs_without_chunks.append(self._doc_summary(document))
            if minio_client is not None and not await self._minio_object_exists(minio_client, document.minio_path):
                minio_missing.append(self._doc_summary(document))

        es = ESClient()
        milvus = MilvusClient()
        embedder = DocumentEmbedder(dense_dim=max(milvus.dim, 1))
        filters = {"tenant_id": tenant_id, "access_level": {"$lte": 9}}
        milvus_health = milvus.health()
        local_embedding_mode = settings.embedding_provider == "local"
        es_missing = []
        milvus_missing = []

        for document in sampled_ready_docs:
            query_text = self._build_doc_probe_query(document, chunks_by_doc.get(document.id, []))
            if not query_text:
                continue
            first_chunk = chunks_by_doc[document.id][0]
            try:
                es_hits = await es.search(query=query_text, filters=filters, top_k=5)
            except (ApiError, TransportError, ESConnectionError, OSError, RuntimeError, TypeError, ValueError):
                es_hits = []
            if not self._hits_contain_doc(es_hits, document.id, document.title):
                es_missing.append(self._doc_summary(document))

            milvus_hits = []
            if milvus_health.get("available"):
                try:
                    query_embedding = embedder.local_embed_query(query_text) if local_embedding_mode else embedder.embed_query(query_text)
                    milvus_hits = await milvus.search(query_embedding, filters, top_k=8)
                except (MilvusException, OSError, RuntimeError, TypeError, ValueError):
                    milvus_hits = []
            if milvus_health.get("available") and not self._hits_contain_doc(milvus_hits, document.id, document.title):
                milvus_missing.append(self._doc_summary(document))

        close = getattr(es, "close", None)
        if close is not None:
            await close()
        neo4j = Neo4jClient()
        neo4j_health = neo4j.health()
        neo4j.close()

        return {
            "tenant_id": tenant_id,
            "stats": {
                "documents": len(docs),
                "ready_documents": len(ready_docs),
                "chunks": len(chunks),
                "ready_chunks": ready_chunk_count,
                "sampled_ready_documents": len(sampled_ready_docs),
                "docs_without_chunks": len(docs_without_chunks),
                "minio_missing_docs": len(minio_missing),
                "es_missing_docs": len(es_missing),
                "milvus_missing_docs": len(milvus_missing),
            },
            "backend_health": {
                "elasticsearch": es.health(),
                "milvus": milvus_health,
                "neo4j": neo4j_health,
            },
            "samples": {
                "docs_without_chunks": docs_without_chunks[:10],
                "minio_missing_docs": minio_missing[:10],
                "es_missing_docs": es_missing[:10],
                "milvus_missing_docs": milvus_missing[:10],
            },
        }

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
        try:
            ESClient().delete_by_tenant(tenant_id)
        except (ApiError, TransportError, ESConnectionError, NotFoundError, OSError, RuntimeError, TypeError, ValueError):
            pass
        try:
            MilvusClient().delete_by_tenant(tenant_id)
        except (MilvusException, OSError, RuntimeError, TypeError, ValueError):
            pass
        try:
            Neo4jClient().delete_by_tenant(tenant_id)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        if chunks:
            try:
                es_count = ESClient().bulk_index(chunks)
            except (ApiError, TransportError, ESConnectionError, NotFoundError, OSError, RuntimeError, TypeError, ValueError):
                es_count = 0
            try:
                dim = len(chunks[0].get("dense_vector", [])) or 12
                milvus_count = MilvusClient(dim=dim).upsert_chunks(chunks)
                if milvus_count < len(chunks):
                    milvus_count = 0
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

    async def _minio_object_exists(self, minio_client, object_path: str) -> bool:
        if not object_path:
            return False
        try:
            await asyncio.to_thread(minio_client.stat_object, settings.minio_bucket, object_path)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _build_doc_probe_query(self, document: Document, chunks: list[DocumentChunk]) -> str:
        parts = [str(document.title or "").strip()]
        if chunks:
            first_chunk = chunks[0]
            if first_chunk.section_title:
                parts.append(str(first_chunk.section_title).strip())
            snippet = (first_chunk.content or "").strip()
            if snippet:
                parts.append(snippet[:120])
        return " ".join(part for part in parts if part)

    def _hits_contain_doc(self, hits: list[dict], doc_id: str, title: str) -> bool:
        normalized_title = str(title or "").strip().lower()
        for item in hits or []:
            if item.get("doc_id") == doc_id:
                return True
            hit_title = str(item.get("document_title") or "").strip().lower()
            if normalized_title and hit_title == normalized_title:
                return True
        return False

    def _doc_summary(self, document: Document) -> dict:
        return {
            "doc_id": document.id,
            "title": document.title,
            "status": document.status,
            "minio_path": document.minio_path,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
        }
