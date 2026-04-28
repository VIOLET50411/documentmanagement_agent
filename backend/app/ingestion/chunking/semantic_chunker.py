"""Semantic chunker using local embedding similarity with overlap fallback."""

from __future__ import annotations

import math
import re
from typing import Iterable

from app.ingestion.embedder import DocumentEmbedder


class SemanticChunker:
    """Split text on semantic boundaries while honoring chunk size limits."""

    def __init__(self, max_tokens: int = 512, overlap_ratio: float = 0.15, similarity_threshold: float = 0.72):
        self.max_tokens = max_tokens
        self.overlap_ratio = overlap_ratio
        self.similarity_threshold = similarity_threshold
        self.embedder = DocumentEmbedder()

    def chunk(self, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized:
            return []

        sentences = self._split_sentences(normalized)
        if not sentences:
            return [normalized]

        groups = self._group_sentences(sentences)
        return self._apply_token_limits(groups)

    def _split_sentences(self, text: str) -> list[str]:
        parts = re.split(r"(?<=[。！？；.!?;])|\n+", text)
        return [part.strip() for part in parts if part and part.strip()]

    def _group_sentences(self, sentences: list[str]) -> list[list[str]]:
        groups: list[list[str]] = []
        current: list[str] = []
        previous_sentence = None

        for sentence in sentences:
            if not current:
                current = [sentence]
                previous_sentence = sentence
                continue

            should_break = False
            combined_tokens = self._estimate_tokens(" ".join(current + [sentence]))
            if combined_tokens > self.max_tokens:
                should_break = True
            elif previous_sentence is not None:
                similarity = self._sentence_similarity(previous_sentence, sentence)
                if similarity < self.similarity_threshold:
                    should_break = True

            if should_break:
                groups.append(current)
                current = self._overlap_tail(current)

            current.append(sentence)
            previous_sentence = sentence

        if current:
            groups.append(current)
        return groups

    def _apply_token_limits(self, groups: Iterable[list[str]]) -> list[str]:
        chunks: list[str] = []
        for group in groups:
            text = self._join_sentences(group)
            if self._estimate_tokens(text) <= self.max_tokens:
                chunks.append(text)
                continue

            words = text.split()
            stride = max(1, int(self.max_tokens * (1 - self.overlap_ratio)))
            for start in range(0, len(words), stride):
                segment = " ".join(words[start : start + self.max_tokens]).strip()
                if segment:
                    chunks.append(segment)
                if start + self.max_tokens >= len(words):
                    break
        return chunks

    def _overlap_tail(self, sentences: list[str]) -> list[str]:
        overlap_tokens = max(1, math.floor(self.max_tokens * self.overlap_ratio))
        kept: list[str] = []
        running = 0
        for sentence in reversed(sentences):
            kept.append(sentence)
            running += self._estimate_tokens(sentence)
            if running >= overlap_tokens:
                break
        return list(reversed(kept))

    def _sentence_similarity(self, left: str, right: str) -> float:
        left_vector = self.embedder.local_embed_query(left)["dense"]
        right_vector = self.embedder.local_embed_query(right)["dense"]
        return self._cosine_similarity(left_vector, right_vector)

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        length = min(len(left), len(right))
        numerator = sum(left[i] * right[i] for i in range(length))
        left_norm = math.sqrt(sum(left[i] * left[i] for i in range(length))) or 1.0
        right_norm = math.sqrt(sum(right[i] * right[i] for i in range(length))) or 1.0
        return numerator / (left_norm * right_norm)

    def _join_sentences(self, sentences: list[str]) -> str:
        text = " ".join(sentence.strip() for sentence in sentences if sentence.strip()).strip()
        return text

    def _estimate_tokens(self, text: str) -> int:
        spaced_tokens = len(text.split())
        cjk_units = re.findall(r"[\u4e00-\u9fff]{1,2}|[A-Za-z0-9]+", text)
        if spaced_tokens > 1:
            return max(spaced_tokens, len(cjk_units))
        return max(1, len(cjk_units))
