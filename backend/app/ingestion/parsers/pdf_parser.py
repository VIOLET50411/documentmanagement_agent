"""PDF parser with optional high-fidelity backends and OCR fallback."""

from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.parsers.ocr_parser import OCRParser

try:
    from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError
except ImportError:  # pragma: no cover - optional dependency
    PDFInfoNotInstalledError = PDFPageCountError = PDFSyntaxError = ()


class PDFParser:
    """Parse PDFs with optional `unstructured`/`pypdf` support."""

    def __init__(self) -> None:
        self.ocr_parser = OCRParser()

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)

        # Prefer the lightweight native-text path first. This avoids public-corpus
        # exports and ordinary text PDFs blocking on heavy hi-res model downloads.
        for parser in (self._parse_with_pypdf, self._parse_with_unstructured):
            try:
                elements = parser(path)
            except (OSError, RuntimeError, ValueError, TypeError):
                elements = []
            if elements:
                return elements

        ocr_elements = self.ocr_parser.parse(file_path)
        if ocr_elements and not all(item.get("type") == "ocr_notice" for item in ocr_elements):
            return ocr_elements

        return self._fallback_notice(path, reason="pdf_text_unavailable")

    def _parse_with_unstructured(self, path: Path) -> list[dict]:
        try:
            from unstructured.partition.pdf import partition_pdf
        except ImportError:
            return []
        try:
            elements = partition_pdf(
                filename=str(path),
                strategy="hi_res",
                infer_table_structure=True,
                include_metadata=True,
                languages=["chi_sim", "eng"],
            )
        except (ImportError, PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError, OSError, RuntimeError, ValueError, TypeError):
            return []
        parsed: list[dict] = []
        for element_index, item in enumerate(elements, start=1):
            text = str(item).strip()
            if not text:
                continue
            metadata = item.metadata.to_dict() if getattr(item, "metadata", None) else {}
            page_number = metadata.get("page_number")
            category = getattr(item, "category", "paragraph") or "paragraph"
            parsed.append(
                {
                    "type": self._normalize_type(category),
                    "text": text,
                    "metadata": {
                        "page_number": page_number,
                        "section_title": metadata.get("section_title") or metadata.get("filename") or path.stem,
                        "element_index": element_index,
                        "char_count": len(text),
                        "file_name": path.name,
                        "parser": "unstructured",
                    },
                }
            )
        return parsed

    def _parse_with_pypdf(self, path: Path) -> list[dict]:
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError, PdfStreamError
        except ImportError:
            return []

        try:
            reader = PdfReader(str(path))
        except (OSError, ValueError, PdfReadError, PdfStreamError):
            return []
        parsed: list[dict] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            blocks = self._split_text_blocks(text)
            if blocks:
                parsed.append(
                    {
                        "type": "paragraph",
                        "text": f"PDF第{page_index}页概览：共提取{len(blocks)}个文本块。",
                        "metadata": {
                            "page_number": page_index,
                            "section_title": path.stem,
                            "block_index": 0,
                            "char_count": len(blocks),
                            "file_name": path.name,
                            "parser": "pypdf_overview",
                        },
                    }
                )
            for block_index, block in enumerate(blocks, start=1):
                element_type = self._infer_block_type(block)
                parsed.append(
                    {
                        "type": element_type,
                        "text": block,
                        "metadata": {
                            "page_number": page_index,
                            "section_title": self._guess_section_title(block, path.stem),
                            "block_index": block_index,
                            "char_count": len(block),
                            "file_name": path.name,
                            "parser": "pypdf",
                        },
                    }
                )
        return parsed

    def _split_text_blocks(self, text: str) -> list[str]:
        text = text.replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        raw_blocks = re.split(r"\n{2,}", text)
        blocks: list[str] = []
        for block in raw_blocks:
            cleaned = re.sub(r"\n+", " ", block).strip()
            if len(cleaned) >= 8:
                blocks.append(cleaned)
        return blocks

    def _guess_section_title(self, text: str, fallback: str) -> str:
        first_line = re.split(r"[。！？\n]", text, maxsplit=1)[0].strip()
        if 2 <= len(first_line) <= 40:
            return first_line
        return fallback

    def _normalize_type(self, raw_type: str) -> str:
        lowered = raw_type.lower()
        if "table" in lowered:
            return "table"
        if "title" in lowered or "header" in lowered:
            return "heading"
        return "paragraph"

    def _infer_block_type(self, text: str) -> str:
        compact = text.strip()
        if not compact:
            return "paragraph"
        if re.fullmatch(r"[\u4e00-\u9fff一二三四五六七八九十0-9A-Za-z\-.、()（） ]{1,40}", compact):
            return "heading"
        if "|" in compact and compact.count("|") >= 2:
            return "table"
        if re.search(r"(表\d+|附表|项目|金额|部门|日期)", compact[:40]) and compact.count(" ") >= 2:
            return "table"
        return "paragraph"

    def _fallback_notice(self, path: Path, reason: str) -> list[dict]:
        return [
            {
                "type": "ocr_notice",
                "text": f"文件 {path.name} 暂时无法提取可用文本，已标记为待 OCR 或人工复核。",
                "metadata": {
                    "page_number": 1,
                    "requires_ocr": True,
                    "ocr_pending": True,
                    "parser": "fallback",
                    "reason": reason,
                    "file_name": path.name,
                },
            }
        ]
