"""Shared ingestion pipeline for both online and batch processing."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.chunking.parent_child_splitter import ParentChildSplitter
from app.ingestion.embedder import DocumentEmbedder
from app.ingestion.graph_extractor import GraphExtractor
from app.ingestion.metadata.tagger import MetadataTagger
from app.security.sanitizer import DocumentSanitizer


class DocumentIngestionPipeline:
    """Run the ingestion pipeline with real AI model support and local fallback."""

    def __init__(self):
        self.splitter = ParentChildSplitter()
        self.tagger = MetadataTagger()
        self.embedder = DocumentEmbedder()
        self.graph_extractor = GraphExtractor()
        self.sanitizer = DocumentSanitizer()

    def parse_file(self, file_path: str, metadata: dict) -> dict:
        parser = self._resolve_parser(metadata.get("file_type", ""), file_path)
        elements = parser.parse(file_path)
        return {"elements": elements, "parser": parser.__class__.__name__}

    def process_elements(self, elements: list[dict], metadata: dict) -> dict:
        chunks = self.splitter.split(elements)
        tagged_chunks = self.tagger.tag(
            chunks,
            metadata | {"file_name": metadata.get("file_name") or "unknown"},
        )
        safe_chunks = self.sanitizer.scan_chunks(tagged_chunks)
        embedded_chunks = self.embedder.embed(safe_chunks)
        graph_triples = self.graph_extractor.extract_and_store_sync(embedded_chunks)
        return {
            "elements": elements,
            "chunks": embedded_chunks,
            "graph_triples": graph_triples,
            "stats": {
                "element_count": len(elements),
                "chunk_count": len(embedded_chunks),
                "parent_count": sum(1 for chunk in embedded_chunks if chunk.get("is_parent")),
                "child_count": sum(1 for chunk in embedded_chunks if not chunk.get("is_parent")),
                "graph_triple_count": len(graph_triples),
            },
        }

    def process_file(self, file_path: str, metadata: dict) -> dict:
        parsed = self.parse_file(file_path, metadata)
        return self.process_elements(
            parsed["elements"],
            metadata | {"file_name": metadata.get("file_name") or Path(file_path).name},
        )

    def _resolve_parser(self, file_type: str, file_path: str):
        from app.ingestion.parsers.docx_parser import DocxParser
        from app.ingestion.parsers.excel_parser import ExcelParser
        from app.ingestion.parsers.html_parser import HTMLParser
        from app.ingestion.parsers.ocr_parser import OCRParser
        from app.ingestion.parsers.pdf_parser import PDFParser
        from app.ingestion.parsers.pptx_parser import PptxParser

        suffix = Path(file_path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
            return OCRParser()
        if suffix in {".html", ".htm"} or "html" in file_type:
            return HTMLParser()
        if "pdf" in file_type or suffix == ".pdf":
            return PDFParser()
        if "word" in file_type or suffix == ".docx":
            return DocxParser()
        if "excel" in file_type or "spreadsheet" in file_type or suffix in {".xlsx", ".csv"}:
            return ExcelParser()
        if "presentation" in file_type or suffix == ".pptx":
            return PptxParser()
        return ExcelParser() if suffix in {".csv", ".xlsx"} else PDFParser()
