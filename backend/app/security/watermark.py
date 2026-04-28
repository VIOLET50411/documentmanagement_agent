"""Invisible watermarking for DLP traceability."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


class Watermarker:
    """Inject invisible digital watermarks into generated text for leak tracing."""

    ZERO = "\u200b"
    ONE = "\u200c"

    @staticmethod
    def build_fingerprint(user_id: str, timestamp: str) -> str:
        return hashlib.md5(f"{user_id}:{timestamp}".encode()).hexdigest()[:16]

    def inject(self, text: str, user_id: str, timestamp: str | None = None) -> str:
        """Inject an invisible watermark encoding `user_id + timestamp`."""
        if not timestamp:
            timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

        fingerprint = self.build_fingerprint(user_id, timestamp)
        watermark = self._encode(fingerprint)
        paragraphs = text.split("\n\n")

        if len(paragraphs) > 1:
            paragraphs[0] = paragraphs[0] + watermark
            return "\n\n".join(paragraphs)

        return text + watermark

    def strip(self, text: str) -> str:
        """Remove watermark characters before presenting text to users or caches."""
        return "".join(char for char in text if char not in (self.ZERO, self.ONE))

    def extract(self, text: str) -> str | None:
        """Extract watermark from text for leak investigation."""
        zero_width_chars = [char for char in text if char in (self.ZERO, self.ONE)]
        if not zero_width_chars:
            return None
        return self._decode("".join(zero_width_chars))

    def _encode(self, data: str) -> str:
        binary = bin(int(data, 16))[2:]
        return "".join(self.ONE if bit == "1" else self.ZERO for bit in binary)

    def _decode(self, watermark: str) -> str:
        binary = "".join("1" if char == self.ONE else "0" for char in watermark)
        return hex(int(binary, 2))[2:]
