#!/usr/bin/env python3
"""Rebuild low-quality SWU HTML documents from local raw sources."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.ingestion.pipeline import DocumentIngestionPipeline
from app.ingestion.tasks import _persist_chunks, _set_document_status, _sync_external_indices
from app.retrieval.es_client import ESClient
from app.retrieval.milvus_client import MilvusClient


def _normalize_title(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\.(html?|pdf|docx?|xlsx?|csv|txt)$", "", value)
    value = (
        value.replace("“", "")
        .replace("”", "")
        .replace('"', "")
        .replace("‘", "")
        .replace("’", "")
        .replace("'", "")
        .replace("《", "")
        .replace("》", "")
    )
    value = re.sub(r"[\s\-—_]+", "", value)
    return value


def _load_manifest_sources() -> dict[str, Path]:
    manifest_path = ROOT / "datasets" / "swu_public_docs" / "sources.json"
    items = json.loads(manifest_path.read_text(encoding="utf-8"))
    mapping: dict[str, Path] = {}
    for item in items:
        saved_path = Path(str(item.get("saved_path") or ""))
        if saved_path.suffix.lower() not in {".html", ".htm"}:
            continue
        key = _normalize_title(item.get("title") or saved_path.stem)
        if key:
            mapping[key] = saved_path
    return mapping


def _fetch_target_documents(max_chunks: int, include_patterns: list[str]) -> list[dict]:
    where = ["file_type = 'text/html'", "chunk_count <= %s"]
    params: list[object] = [max_chunks]
    if include_patterns:
        pattern_sql = []
        for pattern in include_patterns:
            pattern_sql.append("(title ~* %s OR file_name ~* %s)")
            params.extend([pattern, pattern])
        where.append("(" + " OR ".join(pattern_sql) + ")")

    sql = f"""
        select id, tenant_id, title, file_name, file_type, file_size, minio_path,
               department, access_level, uploader_id, effective_date, status, chunk_count
        from documents
        where {' and '.join(where)}
        order by chunk_count asc, updated_at desc
    """
    conn = psycopg2.connect(settings.postgres_dsn_sync)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _resolve_source_path(doc: dict, manifest_sources: dict[str, Path]) -> Path | None:
    candidates = [
        _normalize_title(doc.get("title")),
        _normalize_title(doc.get("file_name")),
    ]
    for key in candidates:
        path = manifest_sources.get(key)
        if path and path.exists():
            return path
    return None


def _rebuild_document(doc: dict, source_path: Path) -> dict:
    metadata = {
        "doc_id": doc["id"],
        "tenant_id": doc["tenant_id"],
        "title": doc["title"],
        "file_name": doc["file_name"],
        "file_type": doc["file_type"],
        "file_size": doc["file_size"],
        "department": doc["department"],
        "access_level": doc["access_level"],
        "uploader_id": doc["uploader_id"],
        "effective_date": doc.get("effective_date"),
    }

    pipeline = DocumentIngestionPipeline()
    _set_document_status(doc["id"], "parsing")
    result = pipeline.process_file(str(source_path), metadata)
    chunks = result["chunks"]
    graph_triples = result["graph_triples"]
    if not chunks:
        raise ValueError("重建后仍未生成任何 chunk")

    _set_document_status(doc["id"], "indexing")
    ESClient().delete_by_doc(doc["id"])
    MilvusClient(dim=len(chunks[0].get("dense_vector", [])) if chunks else 64).delete_by_doc(doc["id"])
    _persist_chunks(doc["id"], chunks, graph_triples)
    index_result = _sync_external_indices(doc["id"], chunks)

    degraded_backends = [name for name, item in index_result.items() if not item.get("ok")]
    final_status = "partial_failed" if degraded_backends else "ready"
    error_message = "; ".join(item["error"] for item in index_result.values() if item.get("error")) or None
    _set_document_status(doc["id"], final_status, chunk_count=len(chunks), error_message=error_message)

    return {
        "id": doc["id"],
        "title": doc["title"],
        "source_path": str(source_path),
        "old_chunk_count": int(doc.get("chunk_count") or 0),
        "new_chunk_count": len(chunks),
        "graph_triples": len(graph_triples),
        "status": final_status,
        "degraded_backends": degraded_backends,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild low-quality SWU HTML docs from local raw HTML files")
    parser.add_argument("--max-chunks", type=int, default=30)
    parser.add_argument("--include-pattern", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest_sources = _load_manifest_sources()
    documents = _fetch_target_documents(args.max_chunks, args.include_pattern)
    if args.limit > 0:
        documents = documents[: args.limit]

    matched: list[dict] = []
    unresolved: list[dict] = []
    for doc in documents:
        source_path = _resolve_source_path(doc, manifest_sources)
        if source_path is None:
            unresolved.append({"id": doc["id"], "title": doc["title"], "file_name": doc["file_name"]})
            continue
        matched.append({"doc": doc, "source_path": source_path})

    if args.dry_run:
        print(
            json.dumps(
                {
                    "target_count": len(documents),
                    "matched_count": len(matched),
                    "unresolved_count": len(unresolved),
                    "matched": [
                        {
                            "id": item["doc"]["id"],
                            "title": item["doc"]["title"],
                            "chunk_count": item["doc"]["chunk_count"],
                            "source_path": str(item["source_path"]),
                        }
                        for item in matched
                    ],
                    "unresolved": unresolved,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    rebuilt: list[dict] = []
    failed: list[dict] = []
    for item in matched:
        doc = item["doc"]
        source_path = item["source_path"]
        try:
            rebuilt.append(_rebuild_document(doc, source_path))
        except Exception as exc:  # pragma: no cover - operational path
            _set_document_status(doc["id"], "failed", error_message=str(exc))
            failed.append(
                {
                    "id": doc["id"],
                    "title": doc["title"],
                    "source_path": str(source_path),
                    "error": str(exc),
                }
            )

    print(
        json.dumps(
            {
                "target_count": len(documents),
                "matched_count": len(matched),
                "rebuilt_count": len(rebuilt),
                "failed_count": len(failed),
                "unresolved_count": len(unresolved),
                "rebuilt": rebuilt,
                "failed": failed,
                "unresolved": unresolved,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
