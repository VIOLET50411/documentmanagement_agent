"""HTML parser for enterprise policy documents."""

from __future__ import annotations

import re
from pathlib import Path


class HTMLParser:
    """Parse HTML documents into structured text elements."""

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            try:
                raw = path.read_bytes().decode("gb18030", errors="ignore")
            except (OSError, UnicodeDecodeError):
                return self._fallback_notice(path, "html_read_failed")

        text = self._strip_html(raw)
        if not text or len(text.strip()) < 20:
            return self._fallback_notice(path, "html_empty_content")

        blocks = self._split_blocks(text)
        if not blocks:
            return self._fallback_notice(path, "html_no_blocks")

        parsed: list[dict] = []
        for idx, block in enumerate(blocks, start=1):
            element_type = self._infer_type(block)
            parsed.append(
                {
                    "type": element_type,
                    "text": block,
                    "metadata": {
                        "page_number": 1,
                        "section_title": self._guess_section(block, path.stem),
                        "block_index": idx,
                        "char_count": len(block),
                        "file_name": path.name,
                        "parser": "html",
                    },
                }
            )
        return parsed

    def _strip_html(self, html: str) -> str:
        """Remove HTML tags, scripts, styles and decode entities."""
        # Remove script/style blocks
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML comments
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        # Convert block-level tags to newlines
        text = re.sub(r"<(?:br|p|div|tr|li|h[1-6]|section|article|header|footer|blockquote)[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Convert table cells to spaces
        text = re.sub(r"<(?:td|th)[^>]*>", " ", text, flags=re.IGNORECASE)
        # Remove remaining tags
        text = re.sub(r"<[^>]+>", "", text)
        # Decode common HTML entities
        entity_map = {
            "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
            "&quot;": '"', "&apos;": "'", "&#8226;": "·", "&mdash;": "—",
            "&ndash;": "–", "&ldquo;": "\u201c", "&rdquo;": "\u201d",
            "&lsquo;": "\u2018", "&rsquo;": "\u2019",
        }
        for entity, char in entity_map.items():
            text = text.replace(entity, char)
        # Decode numeric entities
        text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
        text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _split_blocks(self, text: str) -> list[str]:
        """Split text into meaningful blocks."""
        raw_blocks = re.split(r"\n{2,}", text)
        blocks: list[str] = []
        for block in raw_blocks:
            cleaned = re.sub(r"\n+", " ", block).strip()
            if len(cleaned) >= 8:
                blocks.append(cleaned)
        return blocks

    def _infer_type(self, text: str) -> str:
        compact = text.strip()
        if not compact:
            return "paragraph"
        if re.fullmatch(r"[\u4e00-\u9fff\w\s\-.、()（）：:]{1,50}", compact):
            return "heading"
        if "|" in compact and compact.count("|") >= 2:
            return "table"
        return "paragraph"

    def _guess_section(self, text: str, fallback: str) -> str:
        first_line = re.split(r"[。！？\n]", text, maxsplit=1)[0].strip()
        if 2 <= len(first_line) <= 40:
            return first_line
        return fallback

    def _fallback_notice(self, path: Path, reason: str) -> list[dict]:
        return [
            {
                "type": "ocr_notice",
                "text": f"文件 {path.name} 的 HTML 内容暂时无法提取，已标记为待人工复核。",
                "metadata": {
                    "page_number": 1,
                    "requires_ocr": False,
                    "parser": "html_fallback",
                    "reason": reason,
                    "file_name": path.name,
                },
            }
        ]
