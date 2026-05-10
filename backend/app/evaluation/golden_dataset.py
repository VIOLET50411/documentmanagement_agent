"""Golden dataset generation with deterministic, document-grounded QA synthesis."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation


DEFAULT_TITLE = "未命名文档"
DOC_TITLE = "文档"
SYNTHETIC_DOC_TITLE = "示例文档"
CJK_STOPWORDS = {
    "以及",
    "进行",
    "相关",
    "根据",
    "对于",
    "其中",
    "本条",
    "本办法",
    "本制度",
    "应当",
    "可以",
}
HEADER_ALIASES = {
    "policy": "事项",
    "owner": "负责部门",
    "amount": "金额",
}


class GoldenDatasetGenerator:
    """Generate structured QA pairs from business documents without LLM access."""

    SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")
    DATE_RE = re.compile(r"(20\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?|20\d{2}-\d{1,2}-\d{1,2})")
    VERSION_HINT_RE = re.compile(r"(20\d{2}|修订|版本|版|生效|执行|effective|revised)", re.IGNORECASE)

    async def generate(self, documents: list, count: int = 500) -> list:
        pairs: list[dict] = []
        seen_signatures: set[str] = set()
        doc_candidates: list[list[dict]] = []
        doc_summaries: list[dict] = []

        for document in documents:
            title = document.get("title") or document.get("doc_title") or DEFAULT_TITLE
            snippets = document.get("snippets") or document.get("chunks") or []
            normalized_title = self._humanize_title(title)
            candidates: list[dict] = []
            snippet_signatures: set[str] = set()
            logical_index = 0

            for snippet in snippets[:12]:
                text = (snippet.get("content") or snippet.get("snippet") or "").strip()
                if not text:
                    continue
                normalized_text = re.sub(r"\s+", " ", text)
                signature = normalized_text[:240]
                if signature in snippet_signatures:
                    continue
                snippet_signatures.add(signature)
                if not self._is_eval_worthy_snippet(normalized_text):
                    continue
                logical_index += 1
                table_pairs = self._build_table_pairs(normalized_title, text, document, limit=max(count, 1))
                sentence_pairs = self._build_sentence_pairs(normalized_title, text, document, logical_index - 1)
                candidates.extend(table_pairs)
                candidates.extend(sentence_pairs)
                if len(candidates) >= count:
                    break

            if candidates:
                doc_compare_pair = self._build_doc_level_compare_pair(normalized_title, document, candidates)
                if doc_compare_pair is not None:
                    candidates.append(doc_compare_pair)
                doc_candidates.append(candidates)
                summary = self._build_document_summary(document, normalized_title, candidates)
                if summary is not None:
                    doc_summaries.append(summary)

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

        for item in self._build_cross_document_pairs(doc_summaries):
            if self._append_unique_pair(pairs, seen_signatures, item, count):
                return pairs[:count]

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
        row_summaries: list[tuple[str, str]] = []
        for raw_row in rows[2:]:
            values = [cell.strip() for cell in raw_row.strip("|").split("|")]
            if len(values) != len(headers):
                continue
            subject = values[0]
            if not subject or subject == "---":
                continue

            summary = self._build_row_summary(title, subject, headers[1:], values[1:])
            row_summaries.append((subject, summary))
            for header, value in zip(headers[1:], values[1:]):
                if not value or value == "---":
                    continue
                display_header = self._display_header(header)
                pairs.append(
                    self._make_pair(
                        question=f"{subject}的{display_header}是什么？",
                        answer=value,
                        reference=value,
                        contexts=[summary],
                        context_doc_ids=[document.get("doc_id") or document.get("id")],
                        difficulty="basic" if not self._looks_numeric(value) else "numeric",
                        task_type="field_lookup",
                    )
                )
                if len(pairs) >= limit:
                    return pairs

        if len(row_summaries) >= 2:
            left_subject, left_summary = row_summaries[0]
            right_subject, right_summary = row_summaries[1]
            compare_answer = (
                "| 对象 | 要点 |\n"
                "| --- | --- |\n"
                f"| {left_subject} | {left_summary} |\n"
                f"| {right_subject} | {right_summary} |"
            )
            pairs.append(
                self._make_pair(
                    question=f"根据{title}，{left_subject}和{right_subject}的要求有什么差异？",
                    answer=compare_answer,
                    reference=compare_answer,
                    contexts=[left_summary, right_summary],
                    context_doc_ids=[document.get("doc_id") or document.get("id")],
                    difficulty="compare",
                    task_type="compare",
                )
            )
        return pairs

    def _build_sentence_pairs(self, title: str, text: str, document: dict, index: int) -> list[dict]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []

        sentences = [item.strip() for item in self.SENTENCE_SPLIT_RE.split(cleaned) if item.strip()]
        if not sentences:
            sentences = [cleaned]

        doc_id = document.get("doc_id") or document.get("id")
        first_sentence = sentences[0]
        answer = self._build_reference_answer(cleaned)
        pairs: list[dict] = []
        if first_sentence:
            first_context = self._build_context_excerpt(cleaned, first_sentence)
            pairs.append(
                self._make_pair(
                    question=f"根据{title}，第{index + 1}段开头的原文要求是什么？",
                    answer=first_sentence[:200],
                    reference=first_sentence[:200],
                    contexts=[first_context],
                    context_doc_ids=[doc_id],
                    difficulty="basic",
                    task_type="quote",
                )
            )

        grounded_answer = self._select_grounded_answer(sentences, cleaned)
        if grounded_answer:
            grounded_context = self._build_context_excerpt(cleaned, grounded_answer)
            pairs.append(
                self._make_pair(
                    question=f"根据{title}，这一段明确了什么要求？",
                    answer=grounded_answer[:220],
                    reference=grounded_answer[:220],
                    contexts=[grounded_context],
                    context_doc_ids=[doc_id],
                    difficulty="grounded",
                    task_type="grounded_requirement",
                )
            )
            pairs.append(
                self._make_pair(
                    question=f"如果继续追问{title}里的这项要求，首先需要完成什么动作？",
                    answer=grounded_answer[:220],
                    reference=grounded_answer[:220],
                    contexts=[grounded_context],
                    context_doc_ids=[doc_id],
                    difficulty="follow_up",
                    task_type="follow_up",
                )
            )

        if answer:
            summary_context = self._build_context_excerpt(cleaned, answer)
            pairs.append(
                self._make_pair(
                    question=f"{title}第{index + 1}段的核心内容是什么？",
                    answer=answer,
                    reference=answer,
                    contexts=[summary_context],
                    context_doc_ids=[doc_id],
                    difficulty="basic",
                    task_type="summary",
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
            title_year = self.DATE_RE.search(title)
            if title_year is None:
                return None
            answer = title_year.group(1)
            question = f"根据{title}，当前对应的版本或年份是什么？"
        else:
            date_match = self.DATE_RE.search(sentence)
            answer = sentence[:220]
            question = f"根据{title}，该要求的生效时间或版本信息是什么？"
            if date_match and len(date_match.group(1)) <= 12:
                answer = date_match.group(1)
        return self._make_pair(
            question=question,
            answer=answer,
            reference=answer,
            contexts=[self._build_context_excerpt(cleaned, sentence or answer)],
            context_doc_ids=[doc_id],
            difficulty="versioned",
            task_type="version",
        )

    def _build_cross_document_pairs(self, summaries: list[dict]) -> list[dict]:
        if len(summaries) < 2:
            return []
        pairs: list[dict] = []
        for left, right in zip(summaries, summaries[1:]):
            if left["title"] == right["title"]:
                continue
            answer = (
                "| 维度 | 文档 A | 文档 B |\n"
                "| --- | --- | --- |\n"
                f"| 文档 | 《{left['title']}》 | 《{right['title']}》 |\n"
                f"| 核心要求 | {left['answer']} | {right['answer']} |"
            )
            pairs.append(
                self._make_pair(
                    question=f"比较《{left['title']}》和《{right['title']}》在核心要求上的差异。",
                    answer=answer,
                    reference=answer,
                    contexts=[left["context"], right["context"]],
                    context_doc_ids=[left["doc_id"], right["doc_id"]],
                    difficulty="compare",
                    task_type="cross_doc_compare",
                )
            )
            if len(pairs) >= 2:
                break
        return pairs

    def _build_doc_level_compare_pair(self, title: str, document: dict, candidates: list[dict]) -> dict | None:
        if any(item.get("task_type") == "compare" for item in candidates):
            return None
        comparable = [
            item
            for item in candidates
            if item.get("task_type") in {"summary", "grounded_requirement", "quote"}
            and str(item.get("answer") or "").strip()
        ]
        if len(comparable) < 2:
            return None
        left = comparable[0]
        right = next((item for item in comparable[1:] if item.get("answer") != left.get("answer")), None)
        if right is None:
            return None
        left_answer = str(left.get("answer") or "").strip()[:120]
        right_answer = str(right.get("answer") or "").strip()[:120]
        answer = (
            "| 对比项 | 内容 |\n"
            "| --- | --- |\n"
            f"| 要点一 | {left_answer} |\n"
            f"| 要点二 | {right_answer} |"
        )
        return self._make_pair(
            question=f"根据{title}，文档中的两项核心要求分别是什么，有什么差异？",
            answer=answer,
            reference=answer,
            contexts=[*(left.get("contexts") or [])[:1], *(right.get("contexts") or [])[:1]],
            context_doc_ids=[document.get("doc_id") or document.get("id")],
            difficulty="compare",
            task_type="compare",
        )

    def _build_document_summary(self, document: dict, title: str, candidates: list[dict]) -> dict | None:
        summary_candidate = next(
            (item for item in candidates if item.get("task_type") in {"grounded_requirement", "summary"}),
            None,
        )
        if summary_candidate is None:
            return None
        return {
            "title": title,
            "doc_id": document.get("doc_id") or document.get("id"),
            "answer": str(summary_candidate.get("answer") or "").strip(),
            "context": " ".join(summary_candidate.get("contexts") or []).strip(),
        }

    def _build_reference_answer(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return ""
        sentences = [part.strip() for part in self.SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
        answer = "".join(sentences[:2]).strip()
        return (answer or cleaned)[:220]

    def _is_eval_worthy_snippet(self, text: str) -> bool:
        compact = re.sub(r"\s+", " ", text or "").strip()
        if not compact:
            return False
        table_rows = [line for line in compact.splitlines() if line.strip().startswith("|")]
        if len(table_rows) >= 3:
            return True
        if len(compact) < 80:
            return False
        if "目录" in compact[:80]:
            return False
        if compact.count(".") >= 20 or "................................" in compact:
            return False
        noise_markers = ("附件", "已下载", "当前位置", "版权所有", "访问者", "发布日期")
        if sum(1 for marker in noise_markers if marker in compact) >= 2:
            return False
        if "学校概况" in compact and not any(marker in compact for marker in ("预算", "收入", "支出", "报表", "情况说明")):
            return False
        priority_markers = ("预算", "收入", "支出", "财政", "报表", "情况说明", "金额", "单位：万元", "项目支出")
        if any(marker in compact for marker in priority_markers):
            return True
        return True

    def _select_grounded_answer(self, sentences: list[str], cleaned: str) -> str:
        preferred_keywords = (
            "应当",
            "需要",
            "须",
            "不得",
            "方可",
            "提交",
            "审批",
            "比价",
            "报销",
            "登记",
        )
        for sentence in sentences:
            compact = sentence.strip()
            if compact and any(keyword in compact for keyword in preferred_keywords):
                return compact
        return (sentences[0].strip() if sentences else "") or cleaned[:200]

    def _build_row_summary(self, title: str, subject: str, headers: list[str], values: list[str]) -> str:
        details = [f"{self._display_header(header)}是{value}" for header, value in zip(headers, values) if value and value != "---"]
        joined = "；".join(details)
        return f"{title}中，{subject}：{joined}。"

    def _build_context_excerpt(self, text: str, anchor: str, window: int = 180) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        anchor_text = re.sub(r"\s+", " ", anchor or "").strip()
        if not normalized:
            return ""
        if not anchor_text:
            return normalized[: max(window, 80)]
        position = normalized.find(anchor_text)
        if position < 0:
            sentences = [item.strip() for item in self.SENTENCE_SPLIT_RE.split(normalized) if item.strip()]
            for sentence in sentences:
                if anchor_text[:12] and anchor_text[:12] in sentence:
                    excerpt = sentence[:window]
                    return excerpt if len(excerpt) >= 80 else normalized[: max(window, 80)]
            return normalized[: max(window, 80)]
        start = max(position - 60, 0)
        end = min(position + len(anchor_text) + 90, len(normalized))
        excerpt = normalized[start:end].strip()
        if len(excerpt) < 80 and len(normalized) > len(excerpt):
            extra_end = min(start + max(window, 80), len(normalized))
            excerpt = normalized[start:extra_end].strip()
        return excerpt[: max(window, 80)]

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
