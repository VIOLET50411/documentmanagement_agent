"""Neo4j client for graph indexing and query fallback."""

from __future__ import annotations

import asyncio
import re

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable

from app.config import settings


class Neo4jClient:
    """Best-effort Neo4j graph store used by local GraphRAG fallback."""

    def __init__(self):
        self.driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    def close(self):
        self.driver.close()

    def upsert_triples(self, triples: list[dict]) -> int:
        if not triples:
            return 0
        with self.driver.session() as session:
            count = 0
            for triple in triples:
                session.run(
                    """
                    MERGE (a:Entity {name: $source, tenant_id: $tenant_id})
                    MERGE (b:Entity {name: $target, tenant_id: $tenant_id})
                    MERGE (a)-[r:RELATED {relationship: $relationship, doc_id: $doc_id, tenant_id: $tenant_id, section_title: $section_title}]->(b)
                    """,
                    source=triple.get("source"),
                    target=triple.get("target"),
                    relationship=triple.get("relationship"),
                    doc_id=triple.get("doc_id"),
                    tenant_id=triple.get("tenant_id", "default"),
                    section_title=triple.get("section_title"),
                )
                count += 1
        return count

    async def search(self, query: str, tenant_id: str, top_k: int = 5) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, query, tenant_id, top_k)

    def delete_by_doc(self, doc_id: str) -> int:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH ()-[r:RELATED {doc_id: $doc_id}]-()
                WITH collect(r) AS rels
                FOREACH (r IN rels | DELETE r)
                RETURN size(rels) AS count
                """,
                doc_id=doc_id,
            ).single()
            return int(result["count"]) if result else 0

    def health(self) -> dict:
        try:
            with self.driver.session() as session:
                count = session.run("MATCH ()-[r:RELATED]->() RETURN count(r) AS count").single()
                return {"available": True, "relationships": int(count["count"] if count else 0)}
        except (Neo4jError, ServiceUnavailable, AuthError, OSError, RuntimeError) as exc:
            return {"available": False, "relationships": 0, "error": str(exc)}

    def _search_sync(self, query: str, tenant_id: str, top_k: int) -> list[dict]:
        terms = [term.lower() for term in re.findall(r"[一-鿿A-Za-z0-9]+", query) if term.strip()]
        if not terms:
            terms = [query.lower()]
        cypher = """
        MATCH (a:Entity {tenant_id: $tenant_id})-[r:RELATED {tenant_id: $tenant_id}]->(b:Entity {tenant_id: $tenant_id})
        WHERE any(term IN $terms WHERE toLower(a.name) CONTAINS term OR toLower(b.name) CONTAINS term OR toLower(coalesce(r.section_title, '')) CONTAINS term)
        RETURN a.name AS source, b.name AS target, r.relationship AS relationship, r.doc_id AS doc_id, r.section_title AS section_title
        LIMIT $top_k
        """
        with self.driver.session() as session:
            rows = session.run(cypher, tenant_id=tenant_id, terms=terms, top_k=top_k)
            results = []
            for row in rows:
                results.append(
                    {
                        "doc_id": row["doc_id"],
                        "chunk_id": None,
                        "document_title": row["doc_id"],
                        "snippet": f'{row["source"]} -> {row["target"]}',
                        "page_number": None,
                        "section_title": row["section_title"],
                        "relationship": row["relationship"],
                        "score": 1.0,
                        "source_type": "neo4j",
                    }
                )
            return results
