"""OCR parser with optional PaddleOCR support and graceful fallback."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

try:
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError
except ImportError:  # pragma: no cover - optional dependency
    convert_from_path = None
    PDFInfoNotInstalledError = PDFPageCountError = PDFSyntaxError = ()


class OCRParser:
    """Extract OCR text when an OCR engine is available."""

    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

    def __init__(self) -> None:
        self._engine = None

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        engine = self._get_engine()
        if engine is None:
            return [self._fallback_notice(path, reason="ocr_engine_unavailable")]

        try:
            result = self._ocr_path(engine, path)
        except (OSError, RuntimeError, ValueError, TypeError, PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError):
            return [self._fallback_notice(path, reason="ocr_runtime_failed")]

        elements: list[dict] = []
        for page_index, page in enumerate(self._normalize_pages(result, path), start=1):
            page_lines: list[str] = []
            max_confidence = 0.0
            for line_index, line in enumerate(page or [], start=1):
                normalized = self._normalize_line(line)
                if normalized is None:
                    continue
                text = normalized["text"]
                confidence = normalized["confidence"]
                if not text or confidence < 0.6:
                    continue
                page_lines.append(text)
                max_confidence = max(max_confidence, confidence)
                elements.append(
                    {
                        "type": "ocr_text",
                        "text": text,
                        "metadata": {
                            "page_number": page_index,
                            "line_index": line_index,
                            "confidence": round(confidence, 4),
                            "bbox": normalized["bbox"],
                            "section_title": f"{path.stem} 第{page_index}页",
                            "parser": "paddleocr",
                            "source_type": self._source_type(path),
                        },
                    }
                )
            if page_lines:
                elements.append(
                    {
                        "type": "ocr_page",
                        "text": "\n".join(page_lines),
                        "metadata": {
                            "page_number": page_index,
                            "line_count": len(page_lines),
                            "confidence": round(max_confidence, 4),
                            "section_title": f"{path.stem} 第{page_index}页",
                            "parser": "paddleocr",
                            "source_type": self._source_type(path),
                        },
                    }
                )

        return elements or [self._fallback_notice(path, reason="ocr_empty_result")]

    def _ocr_path(self, engine, path: Path):
        if path.suffix.lower() != ".pdf" or convert_from_path is None:
            return engine.ocr(str(path), cls=True)

        pages = convert_from_path(str(path))
        if not pages:
            return []

        results = []
        with TemporaryDirectory(prefix="docmind-ocr-") as temp_dir:
            temp_root = Path(temp_dir)
            for page_index, page in enumerate(pages, start=1):
                image_path = temp_root / f"page-{page_index}.png"
                page.save(image_path, format="PNG")
                results.append(engine.ocr(str(image_path), cls=True))
        return results

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            self._engine = None
            return None

        self._engine = PaddleOCR(use_angle_cls=True, lang="ch")
        return self._engine

    def _normalize_pages(self, result: Any, path: Path) -> list[list[Any]]:
        if result is None:
            return []
        if path.suffix.lower() == ".pdf":
            return [self._normalize_page(page) for page in result or []]
        return [self._normalize_page(result)]

    def _normalize_page(self, page: Any) -> list[Any]:
        if page is None:
            return []
        if isinstance(page, list) and len(page) == 1 and isinstance(page[0], list):
            first = page[0]
            if first and all(isinstance(item, tuple) and len(item) >= 2 for item in first):
                return first
        if isinstance(page, list):
            return page
        return []

    def _normalize_line(self, line: Any) -> dict[str, Any] | None:
        try:
            bbox = line[0] if isinstance(line[0], (list, tuple)) else []
            raw_text = line[1][0]
            confidence = float(line[1][1] or 0.0)
        except (TypeError, ValueError, IndexError):
            return None
        return {
            "text": str(raw_text or "").strip(),
            "confidence": confidence,
            "bbox": [list(point) for point in bbox] if isinstance(bbox, (list, tuple)) else [],
        }

    def _source_type(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            return "pdf"
        if path.suffix.lower() in self.IMAGE_SUFFIXES:
            return "image"
        return "file"

    def _fallback_notice(self, path: Path, reason: str) -> dict:
        return {
            "type": "ocr_notice",
            "text": f"文件 {path.name} 需要 OCR 才能提取正文，当前已标记为待处理。",
            "metadata": {
                "file_name": path.name,
                "page_number": 1,
                "requires_ocr": True,
                "ocr_pending": True,
                "parser": "fallback",
                "reason": reason,
            },
        }
