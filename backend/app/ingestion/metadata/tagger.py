"""Metadata tagger with deterministic business rules."""

from __future__ import annotations

import re
from pathlib import Path


class MetadataTagger:
    """Tag chunks with department, document type, dates, and sensitivity."""

    TEMP_SECTION_PATTERN = re.compile(r"^tmp[0-9a-z_-]{6,}$", re.IGNORECASE)

    def tag(self, chunks: list[dict], doc_metadata: dict) -> list[dict]:
        title = doc_metadata.get("title") or doc_metadata.get("file_name") or "未命名文档"
        inferred_doc_type = self._infer_doc_type(doc_metadata)
        inferred_department = self._infer_department(title, doc_metadata.get("department"))
        effective_date = doc_metadata.get("effective_date") or self._extract_effective_date(title)

        for chunk in chunks:
            content = chunk.get("content", "")
            keywords = self._extract_keywords(content)
            chunk["tenant_id"] = doc_metadata.get("tenant_id", "default")
            chunk["department"] = inferred_department
            chunk["access_level"] = int(doc_metadata.get("access_level", 1) or 1)
            chunk["doc_id"] = doc_metadata.get("doc_id", "")
            chunk["section_title"] = self._normalize_section_title(chunk.get("section_title"), title)
            chunk["page_number"] = chunk.get("page_number")
            chunk["effective_date"] = effective_date
            chunk["file_type"] = doc_metadata.get("file_type")
            chunk["doc_type"] = inferred_doc_type
            chunk["sensitivity_level"] = self._infer_sensitivity(content)
            chunk["keywords"] = keywords[:12]
            chunk["title"] = title
        return chunks

    def _infer_doc_type(self, doc_metadata: dict) -> str:
        file_name = (doc_metadata.get("file_name") or doc_metadata.get("title") or "").lower()
        suffix = Path(file_name).suffix.lower()
        if suffix in {".csv", ".xlsx"}:
            return "spreadsheet"
        if suffix == ".pdf":
            return "policy_pdf"
        if suffix == ".docx":
            return "word_document"
        return "general_document"

    def _infer_department(self, title: str, explicit_department: str | None) -> str:
        if explicit_department:
            return explicit_department
        lowered = title.lower()
        if any(token in lowered for token in ("财务", "报销", "expense", "travel", "reimburse", "invoice")):
            return "finance"
        if any(token in lowered for token in ("人事", "员工", "年假", "请假", "leave", "employee", "hr")):
            return "hr"
        if any(token in lowered for token in ("法务", "合规", "compliance", "legal", "合同", "regulation")):
            return "legal"
        if any(token in lowered for token in ("采购", "供应商", "purchase", "vendor", "supplier")):
            return "procurement"
        return "public"

    def _infer_sensitivity(self, content: str) -> str:
        if any(token in content for token in ("薪酬", "年薪", "预算", "保密", "机密", "股权", "bank", "账号")):
            return "high"
        if any(token in content for token in ("审批", "合同", "发票", "额度", "授权", "采购", "报销")):
            return "medium"
        return "low"

    def _extract_effective_date(self, text: str) -> str | None:
        matched = re.search(r"(20\d{2}(?:[-/.年]\d{1,2})?(?:[-/.月]\d{1,2})?)", text)
        return matched.group(1) if matched else None

    def _extract_keywords(self, content: str) -> list[str]:
        terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", content or "")
        seen: set[str] = set()
        ordered: list[str] = []
        for term in terms:
            lowered = term.lower()
            if lowered not in seen:
                seen.add(lowered)
                ordered.append(term)
        return ordered

    def _normalize_section_title(self, section_title: str | None, fallback_title: str) -> str:
        normalized = str(section_title or "").strip()
        if not normalized:
            return fallback_title
        if self.TEMP_SECTION_PATTERN.fullmatch(normalized):
            return fallback_title
        return normalized
