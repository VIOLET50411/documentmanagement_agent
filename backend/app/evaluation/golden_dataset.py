"""Golden dataset generation with deterministic, document-grounded QA synthesis."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation


DEFAULT_TITLE = "\u672a\u547d\u540d\u6587\u6863"
DOC_TITLE = "\u6587\u6863"
SYNTHETIC_DOC_TITLE = "\u793a\u4f8b\u6587\u6863"
CJK_STOPWORDS = {
    "\u4ee5\u53ca",
    "\u8fdb\u884c",
    "\u76f8\u5173",
    "\u6839\u636e",
    "\u5bf9\u4e8e",
    "\u5176\u4e2d",
    "\u672c\u6761",
    "\u672c\u529e\u6cd5",
    "\u672c\u5236\u5ea6",
    "\u5e94\u5f53",
    "\u53ef\u4ee5",
}
HEADER_ALIASES = {
    "policy": "\u4e8b\u9879",
    "owner": "\u8d1f\u8d23\u90e8\u95e8",
    "amount": "\u91d1\u989d",
}


class GoldenDatasetGenerator:
    """Generate structured QA pairs from business documents without LLM access."""

    SENTENCE_SPLIT_RE = re.compile(r"(?<=[\u3002\uff01\uff1f\uff1b])")

    async def generate(self, documents: list, count: int = 500) -> list:
        pairs: list[dict] = []
        seen_signatures: set[str] = set()
        doc_candidates: list[list[dict]] = []
        for document in documents:
            title = document.get("title") or document.get("doc_title") or DEFAULT_TITLE
            snippets = document.get("snippets") or document.get("chunks") or []
            normalized_title = self._humanize_title(title)
            candidates: list[dict] = []
            for index, snippet in enumerate(snippets[:6]):
                text = (snippet.get("content") or snippet.get("snippet") or "").strip()
                if not text:
                    continue
                table_pairs = self._build_table_pairs(normalized_title, text, document, limit=max(count, 1))
                snippet_candidates = table_pairs or self._build_sentence_pairs(normalized_title, text, document, index)
                candidates.extend(snippet_candidates)
                if len(candidates) >= count:
                    break
            if candidates:
                doc_candidates.append(candidates)

        if not doc_candidates:
            return []

        positions = [0 for _ in doc_candidates]
        seen_difficulties: set[str] = set()
        primary_rounds = max(1, math.ceil(count / max(1, len(doc_candidates))))
        for _ in range(primary_rounds):
            for idx, candidates in enumerate(doc_candidates):
                selected_index = self._select_candidate_index(candidates, positions[idx], seen_difficulties)
                if selected_index is None:
                    continue
                positions[idx] = selected_index + 1
                if self._append_unique_pair(pairs, seen_signatures, candidates[selected_index], count):
                    return pairs[:count]
                seen_difficulties.add(str(candidates[selected_index].get("difficulty") or "unknown"))

        for idx, candidates in enumerate(doc_candidates):
            for item in candidates[positions[idx]:]:
                if self._append_unique_pair(pairs, seen_signatures, item, count):
                    return pairs[:count]
        return pairs[:count]

    def _append_unique_pair(self, pairs: list[dict], seen_signatures: set[str], item: dict, count: int) -> bool:
        signature = self._signature(item)
        if signature in seen_signatures:
            return False
        seen_signatures.add(signature)
        pairs.append(item)
        return len(pairs) >= count

    def _select_candidate_index(self, candidates: list[dict], start: int, seen_difficulties: set[str]) -> int | None:
        if start >= len(candidates):
            return None
        for index in range(start, len(candidates)):
            difficulty = str(candidates[index].get("difficulty") or "unknown")
            if difficulty not in seen_difficulties:
                return index
        return start

    def _build_table_pairs(self, title: str, text: str, document: dict, limit: int) -> list[dict]:
        rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
        if len(rows) < 3:
            return []

        headers = [cell.strip() for cell in rows[0].strip("|").split("|")]
        if len(headers) < 2:
            return []

        pairs: list[dict] = []
        for raw_row in rows[2:]:
            values = [cell.strip() for cell in raw_row.strip("|").split("|")]
            if len(values) != len(headers):
                continue
            subject = values[0]
            if not subject or subject == "---":
                continue

            summary = self._build_row_summary(title, subject, headers[1:], values[1:])
            for header, value in zip(headers[1:], values[1:]):
                if not value or value == "---":
                    continue
                display_header = self._display_header(header)
                answer = value
                pairs.append(
                    {
                        "question": f"{subject}\u7684{display_header}\u662f\u4ec0\u4e48\uff1f",
                        "answer": answer,
                        "reference": answer,
                        "contexts": [summary],
                        "context_doc_ids": [document.get("doc_id") or document.get("id")],
                        "difficulty": "basic" if not self._looks_numeric(value) else "numeric",
                    }
                )
                if len(pairs) >= limit:
                    return pairs
        return pairs

    def _build_sentence_pairs(self, title: str, text: str, document: dict, index: int) -> list[dict]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []

        sentences = [item.strip() for item in self.SENTENCE_SPLIT_RE.split(cleaned) if item.strip()]
        if not sentences:
            sentences = [cleaned]

        first_sentence = sentences[0]
        answer = self._build_reference_answer(cleaned)
        pairs: list[dict] = []
        if first_sentence:
            pairs.append(
                {
                    "question": f"\u6839\u636e{title}\uff0c\u7b2c{index + 1}\u6bb5\u5f00\u5934\u7684\u539f\u6587\u8981\u6c42\u662f\u4ec0\u4e48\uff1f",
                    "answer": first_sentence[:200],
                    "reference": first_sentence[:200],
                    "contexts": [cleaned],
                    "context_doc_ids": [document.get("doc_id") or document.get("id")],
                    "difficulty": "basic",
                }
            )

        grounded_answer = self._select_grounded_answer(sentences, cleaned)
        if grounded_answer:
            pairs.append(
                {
                    "question": f"\u6839\u636e{title}\uff0c\u8fd9\u4e00\u6bb5\u660e\u786e\u4e86\u4ec0\u4e48\u8981\u6c42\uff1f",
                    "answer": grounded_answer[:200],
                    "reference": grounded_answer[:200],
                    "contexts": [cleaned],
                    "context_doc_ids": [document.get("doc_id") or document.get("id")],
                    "difficulty": "grounded",
                }
            )
        if answer:
            pairs.append(
                {
                    "question": f"{title}\u7b2c{index + 1}\u6bb5\u7684\u6838\u5fc3\u5185\u5bb9\u662f\u4ec0\u4e48\uff1f",
                    "answer": answer,
                    "reference": answer,
                    "contexts": [cleaned],
                    "context_doc_ids": [document.get("doc_id") or document.get("id")],
                    "difficulty": "basic",
                }
            )
        return pairs

    def _build_reference_answer(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return ""
        sentences = [part.strip() for part in self.SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
        answer = "".join(sentences[:2]).strip()
        return (answer or cleaned)[:220]

    def _extract_key_entities(self, text: str) -> list[str]:
        matches = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,20}", text)
        entities: list[str] = []
        for item in matches:
            if item in CJK_STOPWORDS or item.isdigit():
                continue
            if item not in entities:
                entities.append(item)
        return entities

    def _select_grounded_answer(self, sentences: list[str], cleaned: str) -> str:
        preferred_keywords = (
            "\u5e94\u5f53",
            "\u9700\u8981",
            "\u987b",
            "\u4e0d\u5f97",
            "\u65b9\u53ef",
            "\u63d0\u4ea4",
            "\u5ba1\u6279",
            "\u6bd4\u4ef7",
            "\u62a5\u9500",
        )
        for sentence in sentences:
            compact = sentence.strip()
            if compact and any(keyword in compact for keyword in preferred_keywords):
                return compact
        return (sentences[0].strip() if sentences else "") or cleaned[:200]

    def _build_row_summary(self, title: str, subject: str, headers: list[str], values: list[str]) -> str:
        details = [f"{self._display_header(header)}\u662f{value}" for header, value in zip(headers, values) if value and value != "---"]
        joined = "\uff1b".join(details)
        return f"{title}\u4e2d\uff0c{subject}\uff1a{joined}\u3002"

    def _looks_numeric(self, value: str) -> bool:
        normalized = value.replace(",", "").replace("%", "").strip()
        if not normalized:
            return False
        try:
            Decimal(normalized)
            return True
        except InvalidOperation:
            return False

    def _signature(self, item: dict) -> str:
        return f"{item.get('question', '')}||{item.get('answer', '')}"

    def _humanize_title(self, title: str) -> str:
        cleaned = str(title or "").strip()
        if not cleaned:
            return DOC_TITLE
        normalized = cleaned.lower()
        if re.match(r"^(smoke_|tmp_|test_|sample_)", normalized):
            return SYNTHETIC_DOC_TITLE
        return cleaned

    def _display_header(self, header: str) -> str:
        normalized = str(header or "").strip().lower()
        return HEADER_ALIASES.get(normalized, str(header or "").strip())
