"""OCR parser with optional PaddleOCR support and graceful fallback."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from pdf2image import convert_from_path
except ImportError:  # pragma: no cover - optional dependency
    convert_from_path = None


class OCRParser:
    """Extract OCR text when an OCR engine is available."""

    def __init__(self) -> None:
        self._engine = None

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        engine = self._get_engine()
        if engine is None:
            return [self._fallback_notice(path, reason="ocr_engine_unavailable")]

        try:
            result = self._ocr_path(engine, path)
        except (OSError, RuntimeError, ValueError, TypeError):
            return [self._fallback_notice(path, reason="ocr_runtime_failed")]

        elements: list[dict] = []
        for page_index, page in enumerate(result or [], start=1):
            for line in page or []:
                try:
                    text = (line[1][0] or "").strip()
                    confidence = float(line[1][1] or 0.0)
                except (TypeError, ValueError, IndexError):
                    continue
                if not text or confidence < 0.6:
                    continue
                elements.append(
                    {
                        "type": "ocr_text",
                        "text": text,
                        "metadata": {
                            "page_number": page_index,
                            "confidence": round(confidence, 4),
                            "parser": "paddleocr",
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
