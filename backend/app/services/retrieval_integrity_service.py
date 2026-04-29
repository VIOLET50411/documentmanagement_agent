"""Retrieval integrity checks across PostgreSQL, Elasticsearch, Milvus, Neo4j, and embedding backends."""

from __future__ import annotations

import asyncio
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion.embedder import DocumentEmbedder
from app.models.db.document import Document, DocumentChunk
from app.retrieval.es_client import ESClient
from app.retrieval.milvus_client import MilvusClient
from app.retrieval.neo4j_client import Neo4jClient


class RetrievalIntegrityService:
    BACKEND_HEALTH_TIMEOUT_SECONDS = 3.0
    BACKEND_QUERY_TIMEOUT_SECONDS = 2.0

    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate(self, tenant_id: str, sample_size: int = 12) -> dict:
        vector_path_required = bool(settings.hybrid_vector_enabled)
        pg_docs = int(
            await self.db.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)) or 0
        )
        pg_chunks = int(
            await self.db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id))
            or 0
        )

        es = ESClient()
        milvus = MilvusClient()
        neo4j = Neo4jClient()
        try:
            es_health = await self._run_sync_health(es.health, backend="elasticsearch")
            milvus_health = await self._run_sync_health(milvus.health, backend="milvus")
            neo4j_health = await self._run_sync_health(neo4j.health, backend="neo4j")

            rows = await self.db.execute(
                select(
                    DocumentChunk.id,
                    DocumentChunk.doc_id,
                    DocumentChunk.content,
                    DocumentChunk.section_title,
                    Document.title,
                )
                .join(Document, Document.id == DocumentChunk.doc_id)
                .where(DocumentChunk.tenant_id == tenant_id)
                .order_by(DocumentChunk.created_at.desc())
                .limit(max(sample_size, 1))
            )
            samples = rows.all()

            embedder = DocumentEmbedder(dense_dim=max(milvus.dim, 1))
            embedding_health = await self._run_sync_health(embedder.remote_health, backend="embedding")
            local_embedding_mode = (
                settings.embedding_provider == "local"
                or not bool(embedding_health.get("available"))
                or embedding_health.get("mode") in {"local", "degraded"}
            )
            filters = {"tenant_id": tenant_id, "access_level": {"$lte": 9}}

            es_hits = 0
            milvus_hits = 0
            es_missing: list[str] = []
            milvus_missing: list[str] = []

            for chunk_id, doc_id, content, section_title, document_title in samples:
                query_text = self._build_probe_query(content, section_title=section_title, document_title=document_title)
                if not query_text:
                    continue

                es_result = await self._run_async_query(
                    es.search(query_text, filters, top_k=5),
                    backend="elasticsearch",
                )
                if any(
                    self._hit_matches_sample(
                        item,
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        content=content,
                        section_title=section_title,
                        document_title=document_title,
                    )
                    for item in es_result
                ):
                    es_hits += 1
                else:
                    es_missing.append(chunk_id)

                milvus_result: list[dict] = []
                if milvus_health.get("available"):
                    try:
                        query_embedding = (
                            embedder.local_embed_query(query_text)
                            if local_embedding_mode
                            else embedder.embed_query(query_text)
                        )
                        milvus_result = await self._run_async_query(
                            milvus.search(query_embedding, filters, top_k=8),
                            backend="milvus",
                        )
                    except (OSError, RuntimeError, ValueError, TypeError):
                        milvus_result = []
                if any(
                    self._hit_matches_sample(
                        item,
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        content=content,
                        section_title=section_title,
                        document_title=document_title,
                    )
                    for item in milvus_result
                ):
                    milvus_hits += 1
                else:
                    milvus_missing.append(chunk_id)

            effective_samples = max(len([item for item in samples if self._build_probe_query(item[2], section_title=item[3], document_title=item[4])]), 1)
            es_recall = round(es_hits / effective_samples, 4)
            milvus_recall = round(milvus_hits / effective_samples, 4)
            milvus_threshold = 0.0 if (local_embedding_mode or not vector_path_required) else 0.4
            milvus_check_message = (
                "默认检索路径未启用向量召回，Milvus 结果仅作诊断参考"
                if not vector_path_required
                else "Milvus 处于本地向量降级模式时允许召回率为 0"
                if local_embedding_mode
                else "Milvus 样本召回率需达到 40%"
            )

            checks = [
                {
                    "id": "es_presence",
                    "ok": bool(es_health.get("available")) and es_health.get("documents", 0) >= max(int(pg_chunks * 0.8), 0),
                    "severity": "critical",
                    "message": "Elasticsearch 文档量应与 PostgreSQL 分块量基本一致",
                },
                {
                    "id": "milvus_presence",
                    "ok": True
                    if not vector_path_required
                    else bool(milvus_health.get("available")) and milvus_health.get("entities", 0) >= max(int(pg_chunks * 0.8), 0),
                    "severity": "info" if not vector_path_required else ("warning" if local_embedding_mode else "critical"),
                    "applicable": vector_path_required,
                    "message": "Milvus 向量量应与 PostgreSQL 分块量基本一致",
                },
                {
                    "id": "es_sample_recall",
                    "ok": es_recall >= 0.5,
                    "severity": "warning",
                    "message": "Elasticsearch 样本召回率需达到 50%",
                },
                {
                    "id": "milvus_sample_recall",
                    "ok": True if not vector_path_required else milvus_recall >= milvus_threshold,
                    "severity": "info" if not vector_path_required else ("warning" if local_embedding_mode else "critical"),
                    "applicable": vector_path_required,
                    "message": milvus_check_message,
                },
                {
                    "id": "neo4j_available",
                    "ok": bool(neo4j_health.get("available")),
                    "severity": "warning",
                    "message": "Neo4j 需保持可用",
                },
            ]

            scored_checks = [item for item in checks if item.get("applicable", True)]
            blockers = [item for item in scored_checks if not item["ok"]]
            critical_blockers = [item for item in blockers if item.get("severity") == "critical"]
            score = round((len(scored_checks) - len(blockers)) / max(len(scored_checks), 1) * 100, 2)

            return {
                "score": score,
                "healthy": len(critical_blockers) == 0,
                "checks": checks,
                "blockers": blockers,
                "critical_blockers": critical_blockers,
                "stats": {
                    "tenant_id": tenant_id,
                    "pg_documents": pg_docs,
                    "pg_chunks": pg_chunks,
                    "es_documents": es_health.get("documents", 0),
                    "milvus_entities": milvus_health.get("entities", 0),
                    "neo4j_relationships": neo4j_health.get("relationships", 0),
                    "sample_size": len(samples),
                    "es_sample_recall": es_recall,
                    "milvus_sample_recall": milvus_recall,
                    "es_missing_sample_chunk_ids": es_missing[:10],
                    "milvus_missing_sample_chunk_ids": milvus_missing[:10],
                    "embedding_health": embedding_health,
                    "backend_health": {
                        "elasticsearch": es_health,
                        "milvus": milvus_health,
                        "neo4j": neo4j_health,
                        "embedding": embedding_health,
                    },
                },
                "mode": "keyword_graph_default" if not vector_path_required else ("local_embedding_relaxed" if local_embedding_mode else "strict_embedding"),
            }
        finally:
            close = getattr(es, "close", None)
            if close is not None:
                await close()
            neo4j.close()

    def _build_probe_query(self, content: str | None, *, section_title: str | None = None, document_title: str | None = None) -> str:
        text = (content or "").strip()
        prefix = " ".join(part.strip() for part in [document_title or "", section_title or ""] if part and part.strip())
        if prefix:
            text = f"{prefix} {text}".strip()
        if not text:
            return ""
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)
        if tokens:
            unique: list[str] = []
            for token in tokens:
                lowered = token.lower()
                if lowered not in unique:
                    unique.append(lowered)
                if len(unique) >= 8:
                    break
            return " ".join(unique)
        return text[:80]

    def _hit_matches_sample(
        self,
        hit: dict,
        *,
        chunk_id: str,
        doc_id: str | None,
        content: str | None,
        section_title: str | None,
        document_title: str | None,
    ) -> bool:
        if hit.get("chunk_id") == chunk_id:
            return True
        if doc_id and hit.get("doc_id") == doc_id:
            return True

        hit_title = self._normalize_text(hit.get("document_title"))
        hit_section = self._normalize_text(hit.get("section_title"))
        hit_snippet = self._normalize_text(hit.get("snippet"))
        sample_title = self._normalize_text(document_title)
        sample_section = self._normalize_text(section_title)
        sample_content = self._normalize_text(content)

        if sample_title and hit_title and sample_title == hit_title:
            if sample_section and hit_section and sample_section == hit_section:
                return True
            if sample_content and hit_snippet and self._content_fingerprint(sample_content) == self._content_fingerprint(hit_snippet):
                return True

        if sample_content and hit_snippet:
            sample_fp = self._content_fingerprint(sample_content)
            hit_fp = self._content_fingerprint(hit_snippet)
            if sample_fp and sample_fp == hit_fp:
                return True
            if self._token_overlap_ratio(sample_content, hit_snippet) >= 0.75:
                return True

        return False

    def _normalize_text(self, value: str | None) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"\s+", " ", text)
        return text

    def _content_fingerprint(self, text: str) -> str:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)
        return "|".join(tokens[:16])

    def _token_overlap_ratio(self, left: str, right: str) -> float:
        left_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", left))
        right_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", right))
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = left_tokens & right_tokens
        return len(overlap) / max(len(left_tokens), 1)

    async def _run_sync_health(self, fn, *, backend: str) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn), timeout=self.BACKEND_HEALTH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return {"available": False, "status": "timeout", "backend": backend, "error": "health timeout"}
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            return {"available": False, "status": "degraded", "backend": backend, "error": str(exc)}

    async def _run_async_query(self, coro, *, backend: str) -> list[dict]:
        try:
            result = await asyncio.wait_for(coro, timeout=self.BACKEND_QUERY_TIMEOUT_SECONDS)
            return result if isinstance(result, list) else []
        except asyncio.TimeoutError:
            return []
        except (OSError, RuntimeError, ValueError, TypeError):
            return []
