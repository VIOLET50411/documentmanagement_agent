"""Document sanitization against indirect prompt injection."""

from __future__ import annotations

import logging


class DocumentSanitizer:
    """Detect and neutralize indirect prompt injection in retrieved document chunks."""

    INJECTION_PATTERNS = (
        "请忽略之前的内容",
        "忽略以上规则",
        "ignore previous",
        "ignore all",
        "you are now",
        "new instructions",
        "system:",
        "override",
        "reveal secrets",
    )

    def scan_chunks(self, chunks: list) -> list:
        safe_chunks = []
        for chunk in chunks:
            content = self._remove_invisible_chars(chunk.get("content", ""))
            if not self._contains_injection(content):
                chunk["content"] = content
                safe_chunks.append(chunk)
            else:
                logging.warning("Potential injection detected in chunk: %s", chunk.get("chunk_id", "unknown"))
        return safe_chunks

    def _remove_invisible_chars(self, text: str) -> str:
        invisible_chars = ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"]
        for char in invisible_chars:
            text = text.replace(char, "")
        return text

    def _contains_injection(self, text: str) -> bool:
        text_lower = text.lower()
        return any(pattern.lower() in text_lower for pattern in self.INJECTION_PATTERNS)
