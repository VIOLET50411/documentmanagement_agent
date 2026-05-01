"""Golden dataset generation fallback."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


class GoldenDatasetGenerator:
    """Generate structured QA pairs from business documents without LLM access."""

    async def generate(self, documents: list, count: int = 500) -> list:
        pairs = []
        seen_signatures: set[str] = set()
        for document in documents:
            title = document.get("title") or document.get("doc_title") or "未命名文档"
            snippets = document.get("snippets") or document.get("chunks") or []
            for index, snippet in enumerate(snippets[:3]):
                text = (snippet.get("content") or snippet.get("snippet") or "").strip()
                if not text:
                    continue

                table_pairs = self._build_table_pairs(title, text, document, limit=max(count - len(pairs), 0))
                if table_pairs:
                    for item in table_pairs:
                        signature = self._signature(item)
                        if signature in seen_signatures:
                            continue
                        seen_signatures.add(signature)
                        pairs.append(item)
                else:
                    answer = self._build_reference_answer(text)
                    if not answer:
                        continue
                    item = {
                        "question": f"{self._humanize_title(title)}第 {index + 1} 段的核心内容是什么？",
                        "answer": answer,
                        "reference": answer,
                        "contexts": [text],
                        "context_doc_ids": [document.get("doc_id") or document.get("id")],
                        "difficulty": "basic",
                    }
                    signature = self._signature(item)
                    if signature not in seen_signatures:
                        seen_signatures.add(signature)
                        pairs.append(item)
                if len(pairs) >= count:
                    return pairs[:count]
        return pairs[:count]

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
                if not value or value == "---" or self._looks_numeric(value):
                    continue
                answer = f"In {title}, the {header} for {subject} is {value}."
                pairs.append(
                    {
                        "question": f"In {title}, what is the {header} for {subject}?",
                        "answer": answer,
                        "reference": answer,
                        "contexts": [text, summary],
                        "context_doc_ids": [document.get("doc_id") or document.get("id")],
                        "difficulty": "basic",
                    }
                )
                if len(pairs) >= limit:
                    return pairs
        return pairs

    def _build_reference_answer(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return ""
        sentences = re.split(r"(?<=[\u3002\uff01\uff1f!?])", cleaned)
        answer = "".join(part.strip() for part in sentences[:2] if part.strip()).strip()
        return (answer or cleaned)[:200]

    def _build_row_summary(self, title: str, subject: str, headers: list[str], values: list[str]) -> str:
        details = [f"{header} is {value}" for header, value in zip(headers, values) if value and value != "---"]
        joined = ", ".join(details)
        return f"In {title}, {subject}: {joined}."

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
            return "文档中"
        if cleaned.lower().endswith((".csv", ".xlsx", ".xls", ".pdf", ".docx")):
            return cleaned
        return f"{cleaned}中"
