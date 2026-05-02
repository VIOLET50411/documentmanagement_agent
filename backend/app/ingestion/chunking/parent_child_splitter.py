"""Hierarchical parent-child chunking."""

from __future__ import annotations

import math
import uuid

from app.ingestion.chunking.semantic_chunker import SemanticChunker


class ParentChildSplitter:
    """Split parsed elements into parent and child chunks."""

    def __init__(self, parent_max_tokens: int = 2048, child_max_tokens: int = 512, overlap: float = 0.15):
        self.parent_max_tokens = parent_max_tokens
        self.child_max_tokens = child_max_tokens
        self.overlap = overlap
        self.semantic_chunker = SemanticChunker(max_tokens=child_max_tokens, overlap_ratio=overlap)

    def split(self, elements: list) -> list:
        parents = self._build_parents(elements)
        chunks = []
        for parent_index, parent in enumerate(parents):
            parent_id = str(uuid.uuid4())
            parent_text = parent["content"]
            parent_chunk = {
                "id": parent_id,
                "parent_id": None,
                "chunk_index": len(chunks),
                "content": parent_text,
                "content_type": parent.get("type", "text"),
                "section_title": parent.get("section_title"),
                "page_number": parent.get("page_number"),
                "token_count": self._token_count(parent_text),
                "is_parent": True,
                "parser": parent.get("parser"),
                "source_type": parent.get("source_type"),
                "element_types": parent.get("element_types", []),
            }
            chunks.append(parent_chunk)

            for child_index, child_text in enumerate(self._split_text(parent_text, self.child_max_tokens)):
                chunks.append(
                    {
                        "id": str(uuid.uuid4()),
                        "parent_id": parent_id,
                        "chunk_index": len(chunks),
                        "content": child_text,
                        "content_type": parent.get("type", "text"),
                        "section_title": parent.get("section_title") or f"Section {parent_index + 1}",
                        "page_number": parent.get("page_number"),
                        "token_count": self._token_count(child_text),
                        "is_parent": False,
                        "child_order": child_index,
                        "parser": parent.get("parser"),
                        "source_type": parent.get("source_type"),
                    }
                )
        return chunks

    def _build_parents(self, elements: list) -> list:
        parents = []
        buffer = []
        page_number = None
        section_title = None
        parser = None
        source_type = None
        element_types: list[str] = []
        for element in elements:
            text = (element.get("text") or "").strip()
            if not text:
                continue
            metadata = element.get("metadata", {}) or {}
            current_page = metadata.get("page_number", page_number)
            current_section = metadata.get("section_title") or section_title
            current_type = str(element.get("type") or "text")
            current_parser = metadata.get("parser", parser)
            current_source_type = metadata.get("source_type", source_type)
            starts_new_section = current_type == "heading" and buffer
            crosses_page = current_page != page_number and buffer
            exceeds_budget = self._token_count(" ".join(buffer + [text])) > self.parent_max_tokens and buffer

            if starts_new_section or crosses_page or exceeds_budget:
                parents.append(
                    {
                        "content": "\n".join(buffer),
                        "page_number": page_number,
                        "section_title": section_title,
                        "type": self._collapse_type(element_types),
                        "parser": parser,
                        "source_type": source_type,
                        "element_types": list(dict.fromkeys(element_types)),
                    }
                )
                buffer = []
                element_types = []

            if current_type == "heading" and not current_section:
                current_section = text[:80]

            buffer.append(text)
            element_types.append(current_type)
            page_number = current_page
            section_title = current_section
            parser = current_parser
            source_type = current_source_type
        if buffer:
            parents.append(
                {
                    "content": "\n".join(buffer),
                    "page_number": page_number,
                    "section_title": section_title,
                    "type": self._collapse_type(element_types),
                    "parser": parser,
                    "source_type": source_type,
                    "element_types": list(dict.fromkeys(element_types)),
                }
            )
        return parents

    def _collapse_type(self, element_types: list[str]) -> str:
        if any(item == "table" for item in element_types):
            return "table"
        if any(item == "heading" for item in element_types):
            return "heading"
        if any(item == "ocr_page" for item in element_types):
            return "ocr_page"
        return "text"

    def _split_text(self, text: str, max_tokens: int) -> list[str]:
        if self._token_count(text) <= max_tokens:
            return [text]

        semantic_chunks = [chunk.strip() for chunk in self.semantic_chunker.chunk(text) if chunk.strip()]
        if semantic_chunks and all(self._token_count(chunk) <= max_tokens * 2 for chunk in semantic_chunks):
            normalized: list[str] = []
            for chunk in semantic_chunks:
                if self._token_count(chunk) <= max_tokens:
                    normalized.append(chunk)
                    continue
                normalized.extend(self._split_text_by_words(chunk, max_tokens))
            return normalized or [text]

        return self._split_text_by_words(text, max_tokens)

    def _split_text_by_words(self, text: str, max_tokens: int) -> list[str]:
        words = text.split()
        if len(words) <= max_tokens:
            return [text]
        stride = max(1, int(max_tokens * (1 - self.overlap)))
        segments = []
        for start in range(0, len(words), stride):
            segment = words[start:start + max_tokens]
            if not segment:
                break
            segments.append(" ".join(segment))
            if start + max_tokens >= len(words):
                break
        return segments

    def _token_count(self, text: str) -> int:
        return max(1, math.ceil(len(text) / 4))
