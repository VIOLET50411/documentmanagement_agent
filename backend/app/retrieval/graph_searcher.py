"""Fallback graph searcher."""

from __future__ import annotations

import re

from neo4j.exceptions import Neo4jError, ServiceUnavailable
from sqlalchemy import and_, case, or_, select

from app.api.middleware.rbac import build_permission_filter
from app.models.db.document import Document, DocumentChunk
from app.retrieval.neo4j_client import Neo4jClient


class GraphSearcher:
    """Fallback relationship search based on metadata and keyword co-occurrence."""

    async def traverse(self, query: str, user=None, db=None, top_k: int = 5) -> list[dict]:
        if db is None or user is None:
            return []

        client = None
        try:
            client = Neo4jClient()
            live_results = await client.search(query=query, tenant_id=user.tenant_id, top_k=top_k)
            if live_results:
                hydrated = await self._hydrate_live_results(db=db, tenant_id=user.tenant_id, results=live_results)
                return self._dedupe_results(hydrated)[:top_k]
        except (Neo4jError, ServiceUnavailable, OSError, RuntimeError):
            pass
        finally:
            if client is not None:
                client.close()

        filters = build_permission_filter(user)
        terms = self._extract_terms(query)
        conditions = [DocumentChunk.tenant_id == filters["tenant_id"], Document.id == DocumentChunk.doc_id]
        if "access_level" in filters:
            conditions.append(Document.access_level <= filters["access_level"]["$lte"])
        if "department" in filters:
            conditions.append(Document.department.in_(filters["department"]["$in"]))

        score_expr = sum(
            case(
                (
                    or_(
                        DocumentChunk.content.ilike(f"%{term}%"),
                        Document.title.ilike(f"%{term}%"),
                        DocumentChunk.section_title.ilike(f"%{term}%"),
                    ),
                    1,
                ),
                else_=0,
            )
            for term in terms
        )

        rows = await db.execute(
            select(DocumentChunk, Document, score_expr.label("score"))
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(
                and_(*conditions),
                or_(
                    *[
                        or_(
                            DocumentChunk.content.ilike(f"%{term}%"),
                            Document.title.ilike(f"%{term}%"),
                            DocumentChunk.section_title.ilike(f"%{term}%"),
                        )
                        for term in terms
                    ]
                ),
            )
            .order_by(score_expr.desc(), DocumentChunk.chunk_index.asc())
            .limit(top_k)
        )

        results = [
            {
                "doc_id": chunk.doc_id,
                "chunk_id": chunk.id,
                "document_title": document.title,
                "section_title": chunk.section_title,
                "page_number": chunk.page_number,
                "snippet": chunk.content[:300],
                "relationship": self._infer_relationship(query, chunk.content),
                "score": float(score or 0),
                "source_type": "graph",
            }
            for chunk, document, score in rows.all()
        ]
        return self._dedupe_results(results)[:top_k]

    async def _hydrate_live_results(self, db, tenant_id: str, results: list[dict]) -> list[dict]:
        doc_ids = [str(item.get("doc_id") or "").strip() for item in results if str(item.get("doc_id") or "").strip()]
        if not doc_ids:
            return results

        docs_rows = await db.execute(
            select(Document.id, Document.title, Document.department)
            .where(Document.tenant_id == tenant_id, Document.id.in_(doc_ids))
        )
        docs_by_id = {
            str(row.id): {
                "title": row.title,
                "department": row.department,
            }
            for row in docs_rows.all()
        }

        chunk_rows = await db.execute(
            select(
                DocumentChunk.doc_id,
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.page_number,
                DocumentChunk.section_title,
                DocumentChunk.chunk_index,
            )
            .where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.doc_id.in_(doc_ids))
            .order_by(DocumentChunk.doc_id.asc(), DocumentChunk.chunk_index.asc())
        )
        chunks_by_doc: dict[str, list[dict]] = {}
        for row in chunk_rows.all():
            chunks_by_doc.setdefault(str(row.doc_id), []).append(
                {
                    "chunk_id": row.id,
                    "content": row.content,
                    "page_number": row.page_number,
                    "section_title": row.section_title,
                }
            )

        hydrated: list[dict] = []
        for item in results:
            doc_id = str(item.get("doc_id") or "").strip()
            doc_meta = docs_by_id.get(doc_id)
            chunk = self._pick_best_chunk(chunks_by_doc.get(doc_id, []), item.get("section_title"))
            if doc_meta is None and chunk is None:
                continue
            snippet = (chunk or {}).get("content") or item.get("snippet")
            hydrated.append(
                {
                    **item,
                    "chunk_id": item.get("chunk_id") or (chunk or {}).get("chunk_id"),
                    "document_title": (doc_meta or {}).get("title") or item.get("document_title"),
                    "department": (doc_meta or {}).get("department"),
                    "snippet": snippet[:300] if isinstance(snippet, str) else snippet,
                    "page_number": item.get("page_number") or (chunk or {}).get("page_number"),
                    "section_title": (chunk or {}).get("section_title") or item.get("section_title"),
                    "graph_path": item.get("snippet"),
                }
            )
        return hydrated

    def _dedupe_results(self, results: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: set[tuple[str, str, int | None, str]] = set()
        for item in results:
            snippet = str(item.get("snippet") or "").strip()
            key = (
                str(item.get("doc_id") or "").strip(),
                str(item.get("section_title") or "").strip(),
                item.get("page_number"),
                snippet[:160],
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _pick_best_chunk(self, chunks: list[dict], expected_section_title: str | None) -> dict | None:
        if not chunks:
            return None
        normalized_expected = str(expected_section_title or "").strip().lower()
        if normalized_expected:
            for chunk in chunks:
                normalized_section = str(chunk.get("section_title") or "").strip().lower()
                if normalized_section == normalized_expected:
                    return chunk
        return chunks[0]

    def _extract_terms(self, query: str) -> list[str]:
        normalized = re.sub(r"[，。；：！？、]", " ", query)
        parts = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", normalized)
        terms: list[str] = []
        for part in parts:
            terms.append(part)
            if len(part) > 2 and re.search(r"[\u4e00-\u9fff]", part):
                terms.extend(part[i : i + 2] for i in range(len(part) - 1))
        seen = set()
        ordered = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                ordered.append(term)
        return ordered or [query]

    def _infer_relationship(self, query: str, content: str) -> str:
        query_lower = query.lower()
        content_lower = content.lower()
        if "引用" in query or "reference" in query_lower:
            return "references"
        if "修订" in query or "amend" in query_lower or "替代" in content:
            return "amends"
        if "负责" in query or "审批" in content or "负责人" in content:
            return "manages"
        if "上级" in query or "下级" in query or "汇报" in content:
            return "reports_to"
        if "关联" in query or "相关" in query or "协同" in content_lower:
            return "related_to"
        return "related_to"
