"""Batch processing fallback implementation."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.pipeline import DocumentIngestionPipeline


class SparkBatchProcessor:
    """Offline batch processing fallback for historical document migration."""

    def __init__(self, spark_master: str = "local[*]"):
        self.spark_master = spark_master
        self.enabled = False
        self.pipeline = DocumentIngestionPipeline()
        # TODO: [AI_API] and Spark runtime: replace with SparkSession initialization.

    def process_directory(self, input_path: str, tenant_id: str):
        """Process all supported files in a directory using local iteration."""
        base = Path(input_path)
        if not base.exists():
            raise FileNotFoundError(input_path)

        processed = []
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx", ".csv", ".xlsx"}:
                continue
            processed.append(self._parse_file((str(path), tenant_id)))

        return {
            "processor": "local_fallback",
            "spark_master": self.spark_master,
            "tenant_id": tenant_id,
            "processed_count": len(processed),
            "documents": processed,
            "total_chunks": sum(item["chunk_count"] for item in processed),
            "total_graph_triples": sum(item["graph_triple_count"] for item in processed),
        }

    def _parse_file(self, file_tuple):
        """Parse a single file using the shared ingestion pipeline."""
        file_path, tenant_id = file_tuple
        path = Path(file_path)
        result = self.pipeline.process_file(
            str(path),
            {
                "tenant_id": tenant_id,
                "file_name": path.name,
                "title": path.stem,
                "file_type": path.suffix.lower(),
                "doc_id": f"batch::{path.stem}",
                "access_level": 1,
            },
        )
        first_chunk = result["chunks"][0]["content"][:120] if result["chunks"] else ""
        return {
            "file_name": path.name,
            "tenant_id": tenant_id,
            "element_count": result["stats"]["element_count"],
            "chunk_count": result["stats"]["chunk_count"],
            "graph_triple_count": result["stats"]["graph_triple_count"],
            "preview": first_chunk,
        }

    def _embed_and_store(self, partition):
        """Fallback method retained for future interface compatibility."""
        rows = list(partition)
        return {"partition_size": len(rows), "status": "fallback_only"}
