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
                return live_results
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

        return [
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
