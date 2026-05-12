"""Golden dataset generation with deterministic, document-grounded QA synthesis."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

DEFAULT_TITLE = "未命名文档"
SYNTHETIC_DOC_TITLE = "示例文档"
HEADER_ALIASES = {
    "policy": "事项",
    "owner": "负责部门",
    "amount": "金额",
}


class GoldenDatasetGenerator:
    """Generate structured QA pairs from business documents without LLM access."""

    SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")
    DATE_RE = re.compile(r"(20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}-\d{1,2}-\d{1,2}|20\d{2}年)")
    VERSION_HINT_RE = re.compile(r"(20\d{2}|修订|版本|版|生效|执行|effective|revised)", re.IGNORECASE)

    async def generate(self, documents: list, count: int = 500) -> list:
        pairs: list[dict] = []
        seen_signatures: set[str] = set()

        for document in documents:
            title = self._humanize_title(document.get("title") or document.get("doc_title") or DEFAULT_TITLE)
            doc_id = document.get("doc_id") or document.get("id")
            snippets = document.get("snippets") or document.get("chunks") or []

            for index, snippet in enumerate(snippets[:12]):
                text = (snippet.get("content") or snippet.get("snippet") or "").strip()
                if not self._is_eval_worthy_snippet(text):
                    continue

                table_pairs = self._build_table_pairs(title, text, doc_id)
                snippet_pairs = table_pairs or self._build_sentence_pairs(title, text, doc_id, index)
                for item in snippet_pairs:
                    signature = self._signature(item)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    pairs.append(item)
                    if len(pairs) >= count:
                        return pairs[:count]

        return pairs[:count]

    def _build_table_pairs(self, title: str, text: str, doc_id: str | None) -> list[dict]:
        rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
        if len(rows) < 3:
            return []

        headers = [cell.strip() for cell in rows[0].strip("|").split("|")]
        if len(headers) < 2:
            return []

        pairs: list[dict] = []
        seen_rows: set[tuple[str, ...]] = set()
        for raw_row in rows[2:]:
            values = [cell.strip() for cell in raw_row.strip("|").split("|")]
            if len(values) != len(headers):
                continue
            normalized = tuple(values)
            if normalized in seen_rows:
                continue
            seen_rows.add(normalized)

            subject = values[0]
            if not subject or subject == "---":
                continue

            summary = self._build_row_summary(title, subject, headers[1:], values[1:])
            for header, value in zip(headers[1:], values[1:]):
                if not value or value == "---":
                    continue
                display_header = self._display_header(header)
                difficulty = "numeric" if self._looks_numeric(value) else "basic"
                pairs.append(
                    self._make_pair(
                        question=f"{subject}的{display_header}是什么？",
                        answer=value,
                        reference=value,
                        contexts=[summary],
                        context_doc_ids=[doc_id],
                        difficulty=difficulty,
                        task_type="field_lookup",
                    )
                )
        return pairs

    def _build_sentence_pairs(self, title: str, text: str, doc_id: str | None, index: int) -> list[dict]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []

        sentences = [item.strip() for item in self.SENTENCE_SPLIT_RE.split(cleaned) if item.strip()]
        if not sentences:
            sentences = [cleaned]

        pairs: list[dict] = []
        first_sentence = sentences[0][:220]
        pairs.append(
            self._make_pair(
                question=f"根据{title}，第{index + 1}段开头的原文要求是什么？",
                answer=first_sentence,
                reference=first_sentence,
                contexts=[self._build_context_excerpt(cleaned, first_sentence)],
                context_doc_ids=[doc_id],
                difficulty="basic",
                task_type="quote",
            )
        )

        grounded_answer = self._select_grounded_answer(sentences, cleaned)[:220]
        if grounded_answer and grounded_answer != first_sentence:
            pairs.append(
                self._make_pair(
                    question=f"根据{title}，这一段明确了什么要求？",
                    answer=grounded_answer,
                    reference=grounded_answer,
                    contexts=[self._build_context_excerpt(cleaned, grounded_answer)],
                    context_doc_ids=[doc_id],
                    difficulty="grounded",
                    task_type="grounded_requirement",
                )
            )
        else:
            pairs.append(
                self._make_pair(
                    question=f"根据{title}，这一段明确了什么要求？",
                    answer=grounded_answer,
                    reference=grounded_answer,
                    contexts=[self._build_context_excerpt(cleaned, grounded_answer)],
                    context_doc_ids=[doc_id],
                    difficulty="grounded",
                    task_type="grounded_requirement",
                )
            )

        pairs.append(
            self._make_pair(
                question=f"如果继续追问{title}里的这项要求，首先需要完成什么动作？",
                answer=grounded_answer,
                reference=grounded_answer,
                contexts=[self._build_context_excerpt(cleaned, grounded_answer)],
                context_doc_ids=[doc_id],
                difficulty="follow_up",
                task_type="follow_up",
            )
        )

        compare_pair = self._build_intra_document_compare_pair(title, sentences, cleaned, doc_id)
        if compare_pair is not None:
            pairs.append(compare_pair)

        version_pair = self._build_version_pair(title, sentences, cleaned, doc_id)
        if version_pair is not None:
            pairs.append(version_pair)

        return pairs

    def _build_intra_document_compare_pair(
        self,
        title: str,
        sentences: list[str],
        cleaned: str,
        doc_id: str | None,
    ) -> dict | None:
        substantive = [sentence for sentence in sentences if len(sentence) >= 8]
        if len(substantive) < 2:
            return None
        left = substantive[0][:120]
        right = substantive[1][:120]
        if left == right:
            return None
        answer = (
            "| 对比项 | 内容 |\n"
            "| --- | --- |\n"
            f"| 要求一 | {left} |\n"
            f"| 要求二 | {right} |"
        )
        return self._make_pair(
            question=f"根据{title}，前两项要求分别是什么，有什么差异？",
            answer=answer,
            reference=answer,
            contexts=[self._build_context_excerpt(cleaned, left), self._build_context_excerpt(cleaned, right)],
            context_doc_ids=[doc_id],
            difficulty="compare",
            task_type="compare",
        )

    def _build_version_pair(
        self,
        title: str,
        sentences: list[str],
        cleaned: str,
        doc_id: str | None,
    ) -> dict | None:
        sentence = next((item for item in sentences if self.DATE_RE.search(item) and self.VERSION_HINT_RE.search(item)), None)
        if sentence is None and self.VERSION_HINT_RE.search(title):
            sentence = next((item for item in sentences if self.DATE_RE.search(item)), None)
        if sentence is None:
            return None
        date_match = self.DATE_RE.search(sentence)
        answer = date_match.group(1) if date_match else sentence[:220]
        return self._make_pair(
            question=f"根据{title}，该要求的生效时间或版本信息是什么？",
            answer=answer,
            reference=answer,
            contexts=[self._build_context_excerpt(cleaned, sentence)],
            context_doc_ids=[doc_id],
            difficulty="versioned",
            task_type="version",
        )

    def _is_eval_worthy_snippet(self, text: str) -> bool:
        compact = re.sub(r"\s+", " ", text or "").strip()
        if not compact or len(compact) < 8:
            return False
        table_rows = [line for line in (text or "").splitlines() if line.strip().startswith("|")]
        if len(table_rows) >= 3:
            return True
        if "目录" in compact[:40]:
            return False
        noise_markers = ("附件", "已下载", "当前位置", "版权所有", "访问者", "发布日期")
        if sum(1 for marker in noise_markers if marker in compact) >= 2:
            return False
        return True

    def _select_grounded_answer(self, sentences: list[str], cleaned: str) -> str:
        preferred_keywords = ("应当", "需要", "须", "不得", "方可", "提交", "审批", "报销", "登记")
        for sentence in sentences:
            compact = sentence.strip()
            if compact and any(keyword in compact for keyword in preferred_keywords):
                return compact
        return (sentences[0].strip() if sentences else "") or cleaned[:220]

    def _build_row_summary(self, title: str, subject: str, headers: list[str], values: list[str]) -> str:
        details = [f"{self._display_header(header)}是{value}" for header, value in zip(headers, values) if value and value != "---"]
        return f"{title}中，{subject}：{'；'.join(details)}。"

    def _build_context_excerpt(self, text: str, anchor: str, window: int = 180) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        anchor_text = re.sub(r"\s+", " ", anchor or "").strip()
        if not normalized:
            return ""
        if not anchor_text:
            return normalized[:window]
        position = normalized.find(anchor_text)
        if position < 0:
            return normalized[:window]
        start = max(0, position - window // 4)
        end = min(len(normalized), start + window)
        return normalized[start:end].strip()

    def _looks_numeric(self, value: str) -> bool:
        normalized = str(value or "").replace(",", "").strip()
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
            return DEFAULT_TITLE
        normalized = cleaned.lower()
        if re.match(r"^(smoke_|tmp_|test_|sample_)", normalized):
            return SYNTHETIC_DOC_TITLE
        return cleaned

    def _display_header(self, header: str) -> str:
        normalized = str(header or "").strip().lower()
        return HEADER_ALIASES.get(normalized, str(header or "").strip())

    def _make_pair(
        self,
        *,
        question: str,
        answer: str,
        reference: str,
        contexts: list[str],
        context_doc_ids: list[str | None],
        difficulty: str,
        task_type: str,
    ) -> dict:
        return {
            "question": question,
            "answer": answer,
            "reference": reference,
            "contexts": contexts,
            "context_doc_ids": [doc_id for doc_id in context_doc_ids if doc_id],
            "difficulty": difficulty,
            "task_type": task_type,
        }
