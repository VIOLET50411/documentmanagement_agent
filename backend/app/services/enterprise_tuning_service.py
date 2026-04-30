"""企业领域语料导出与训练集治理服务。"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db.document import Document, DocumentChunk


SENSITIVE_TERMS = (
    "身份证",
    "手机号",
    "手机号码",
    "银行卡",
    "工资",
    "薪资",
    "住址",
    "家庭住址",
    "邮箱",
    "电子邮箱",
    "账号",
    "密码",
    "密钥",
    "secret",
    "token",
)

DOC_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("policy", ("制度", "办法", "规范", "细则", "守则", "policy")),
    ("approval", ("审批", "报销", "采购", "合同", "申请", "approval")),
    ("compliance", ("合规", "审计", "风控", "内控", "compliance", "risk")),
    ("hr", ("人事", "绩效", "考勤", "招聘", "员工", "hr")),
    ("meeting", ("会议纪要", "周报", "月报", "汇报", "纪要", "report")),
    ("finance", ("预算", "财务", "付款", "收款", "invoice", "finance")),
)


@dataclass
class ExportCandidate:
    document: Document
    chunk: DocumentChunk
    content: str
    score: int
    fingerprint: str
    sensitivity: str
    category: str


class EnterpriseTuningService:
    """Build CPT / SFT corpora that are usable for later LoRA/SFT pipelines."""

    def __init__(self, db: AsyncSession | None, reports_dir: Path | str):
        self.db = db
        self.reports_dir = Path(reports_dir)

    async def export_domain_corpus(
        self,
        tenant_id: str,
        *,
        doc_limit: int = 200,
        chunk_limit: int = 4000,
        keywords: list[str] | None = None,
        max_access_level: int = 3,
        deduplicate: bool = True,
        train_ratio: float = 0.9,
    ) -> dict:
        if self.db is None:
            return {"ok": False, "message": "数据库会话不可用", "tenant_id": tenant_id}

        terms = [item.strip() for item in (keywords or settings.llm_enterprise_keyword_list) if item.strip()]
        doc_rows = await self.db.execute(
            select(Document)
            .where(Document.tenant_id == tenant_id, Document.status.in_(["ready", "partial_failed"]))
            .order_by(Document.updated_at.desc())
            .limit(max(doc_limit, 1))
        )
        documents = doc_rows.scalars().all()
        document_map = {doc.id: doc for doc in documents}
        if not document_map:
            return {"ok": False, "message": "当前租户没有可用于导出的已处理文档。", "tenant_id": tenant_id}

        chunk_rows = await self.db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.doc_id.in_(list(document_map.keys())))
            .order_by(DocumentChunk.doc_id.asc(), DocumentChunk.chunk_index.asc())
        )
        chunks = chunk_rows.scalars().all()

        prepared: list[ExportCandidate] = []
        excluded: list[dict] = []
        seen_fingerprints: set[str] = set()
        for chunk in chunks:
            document = document_map.get(chunk.doc_id)
            if document is None:
                continue
            content = self._normalize_content(chunk.content)
            if len(content) < settings.llm_enterprise_corpus_min_chars:
                excluded.append(self._excluded_record(document, chunk, "content_too_short"))
                continue
            if int(document.access_level or 1) > max(max_access_level, 1):
                excluded.append(self._excluded_record(document, chunk, "access_level_too_high"))
                continue

            fingerprint = self._content_fingerprint(content)
            if deduplicate and fingerprint in seen_fingerprints:
                excluded.append(self._excluded_record(document, chunk, "duplicate_chunk"))
                continue
            seen_fingerprints.add(fingerprint)

            sensitivity = self._detect_sensitivity(content)
            if sensitivity == "high":
                excluded.append(self._excluded_record(document, chunk, "sensitive_content"))
                continue

            score = self._score_chunk(chunk, document, terms)
            prepared.append(
                ExportCandidate(
                    document=document,
                    chunk=chunk,
                    content=content,
                    score=score,
                    fingerprint=fingerprint,
                    sensitivity=sensitivity,
                    category=self._classify_doc_type(document, chunk),
                )
            )

        ranked = sorted(prepared, key=lambda item: (item.score, item.document.updated_at, item.chunk.chunk_index), reverse=True)
        ranked = ranked[: max(chunk_limit, 1)]
        if not ranked:
            return {"ok": False, "message": "没有满足治理规则的训练片段。", "tenant_id": tenant_id, "excluded_count": len(excluded)}

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_dir = self.reports_dir / "domain_tuning" / tenant_id / timestamp
        return self._write_export_bundle(
            target_dir=target_dir,
            tenant_id=tenant_id,
            ranked=ranked,
            excluded=excluded,
            keywords=terms,
            doc_count=len(document_map),
            doc_limit=max(doc_limit, 1),
            chunk_limit=max(chunk_limit, 1),
            max_access_level=max(max_access_level, 1),
            deduplicate=bool(deduplicate),
            train_ratio=float(train_ratio),
        )

    def export_records_bundle(
        self,
        *,
        tenant_id: str,
        source_label: str,
        records: list[dict],
        train_ratio: float = 0.9,
    ) -> dict:
        ranked: list[ExportCandidate] = []
        excluded: list[dict] = []
        seen_fingerprints: set[str] = set()
        for index, record in enumerate(records):
            title = str(record.get("title") or "未命名文档")
            content = self._normalize_content(str(record.get("content") or ""))
            if len(content) < settings.llm_enterprise_corpus_min_chars:
                excluded.append({"doc_title": title, "reason": "content_too_short", "source_path": record.get("source_path")})
                continue
            fingerprint = self._content_fingerprint(content)
            if fingerprint in seen_fingerprints:
                excluded.append({"doc_title": title, "reason": "duplicate_chunk", "source_path": record.get("source_path")})
                continue
            seen_fingerprints.add(fingerprint)

            sensitivity = self._detect_sensitivity(content)
            if sensitivity == "high":
                excluded.append({"doc_title": title, "reason": "sensitive_content", "source_path": record.get("source_path")})
                continue

            document = self._stub_document(record, index)
            chunk = self._stub_chunk(record, index, content)
            ranked.append(
                ExportCandidate(
                    document=document,
                    chunk=chunk,
                    content=content,
                    score=int(record.get("score") or 1),
                    fingerprint=fingerprint,
                    sensitivity=sensitivity,
                    category=self._classify_doc_type(document, chunk),
                )
            )

        if not ranked:
            return {"ok": False, "message": "没有满足治理规则的公开语料。", "tenant_id": tenant_id, "excluded_count": len(excluded)}

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_dir = self.reports_dir / "domain_tuning" / tenant_id / f"{source_label}_{timestamp}"
        return self._write_export_bundle(
            target_dir=target_dir,
            tenant_id=tenant_id,
            ranked=ranked,
            excluded=excluded,
            keywords=settings.llm_enterprise_keyword_list,
            doc_count=len(ranked),
            doc_limit=len(ranked),
            chunk_limit=len(ranked),
            max_access_level=1,
            deduplicate=True,
            train_ratio=float(train_ratio),
        )

    def _write_export_bundle(
        self,
        *,
        target_dir: Path,
        tenant_id: str,
        ranked: list[ExportCandidate],
        excluded: list[dict],
        keywords: list[str],
        doc_count: int,
        doc_limit: int,
        chunk_limit: int,
        max_access_level: int,
        deduplicate: bool,
        train_ratio: float,
    ) -> dict:
        target_dir.mkdir(parents=True, exist_ok=True)

        cpt_path = target_dir / "enterprise_cpt.jsonl"
        sft_path = target_dir / "enterprise_sft.jsonl"
        train_path = target_dir / "enterprise_sft_train.jsonl"
        val_path = target_dir / "enterprise_sft_val.jsonl"
        rejected_path = target_dir / "excluded_records.jsonl"
        manifest_path = target_dir / "manifest.json"

        keyword_hits: Counter[str] = Counter()
        doc_distribution: Counter[str] = Counter()
        category_distribution: Counter[str] = Counter()
        sensitivity_distribution: Counter[str] = Counter()
        sft_records: list[dict] = []

        with cpt_path.open("w", encoding="utf-8", newline="\n") as cpt_file, sft_path.open("w", encoding="utf-8", newline="\n") as sft_file:
            for item in ranked:
                record = self._build_export_record(item, tenant_id)
                for term in keywords:
                    if term.lower() in item.content.lower():
                        keyword_hits[term] += 1
                doc_distribution[item.document.title] += 1
                category_distribution[item.category] += 1
                sensitivity_distribution[item.sensitivity] += 1

                cpt_payload = {
                    **record,
                    "text": self._build_cpt_text(item.document.title, item.chunk.section_title, item.chunk.page_number, item.content),
                }
                cpt_file.write(json.dumps(cpt_payload, ensure_ascii=False) + "\n")

                sft_payload = {
                    "tenant_id": tenant_id,
                    "doc_id": item.document.id,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是企业管理文档助手。回答必须忠于制度原文，不得编造未出现的审批规则、责任人或风险结论。",
                        },
                        {
                            "role": "user",
                            "content": self._build_sft_prompt(item.document.title, item.chunk.section_title, item.chunk.page_number, item.content),
                        },
                        {
                            "role": "assistant",
                            "content": self._build_rule_summary(item.content),
                        },
                    ],
                    "metadata": record,
                }
                sft_file.write(json.dumps(sft_payload, ensure_ascii=False) + "\n")
                sft_records.append(sft_payload)

        with rejected_path.open("w", encoding="utf-8", newline="\n") as rejected_file:
            for item in excluded:
                rejected_file.write(json.dumps(item, ensure_ascii=False) + "\n")

        train_records, val_records = self._split_records(sft_records, train_ratio=train_ratio)
        self._write_jsonl(train_path, train_records)
        self._write_jsonl(val_path, val_records)

        manifest = {
            "ok": True,
            "tenant_id": tenant_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "doc_count": doc_count,
            "chunk_count": len(ranked),
            "excluded_count": len(excluded),
            "doc_limit": doc_limit,
            "chunk_limit": chunk_limit,
            "max_access_level": max_access_level,
            "deduplicate": deduplicate,
            "train_ratio": float(train_ratio),
            "keywords": keywords,
            "paths": {
                "cpt": str(cpt_path),
                "sft_all": str(sft_path),
                "sft_train": str(train_path),
                "sft_val": str(val_path),
                "excluded": str(rejected_path),
            },
            "top_documents": [{"title": title, "count": count} for title, count in doc_distribution.most_common(20)],
            "keyword_hits": [{"keyword": name, "count": count} for name, count in keyword_hits.most_common()],
            "category_distribution": [{"category": name, "count": count} for name, count in category_distribution.most_common()],
            "sensitivity_distribution": [{"sensitivity": name, "count": count} for name, count in sensitivity_distribution.most_common()],
            "excluded_breakdown": self._count_excluded_reasons(excluded),
            "training_readiness": {
                "train_records": len(train_records),
                "val_records": len(val_records),
                "ready_for_lora": len(train_records) >= 20,
                "ready_for_sft": len(train_records) >= 50,
            },
            "notes": [
                "enterprise_cpt.jsonl 适合继续预训练或领域自适应。",
                "enterprise_sft.jsonl 为全部合格监督样本，train/val 已按固定种子拆分。",
                "excluded_records.jsonl 记录了去重、敏感过滤、长度不足等被剔除的样本。",
                "建议优先使用已审核、已生效、低敏感的制度与流程文档，以提高正式训练集质量。",
            ],
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        return manifest

    def _build_export_record(self, item: ExportCandidate, tenant_id: str) -> dict:
        return {
            "tenant_id": tenant_id,
            "doc_id": item.document.id,
            "doc_title": item.document.title,
            "file_name": item.document.file_name,
            "file_type": item.document.file_type,
            "department": item.document.department,
            "access_level": int(item.document.access_level or 1),
            "page_number": item.chunk.page_number,
            "section_title": item.chunk.section_title,
            "content_type": item.chunk.content_type,
            "score": item.score,
            "fingerprint": item.fingerprint,
            "sensitivity": item.sensitivity,
            "category": item.category,
        }

    def _excluded_record(self, document: Document, chunk: DocumentChunk, reason: str) -> dict:
        return {
            "doc_id": document.id,
            "doc_title": document.title,
            "file_name": document.file_name,
            "access_level": int(document.access_level or 1),
            "section_title": chunk.section_title,
            "page_number": chunk.page_number,
            "chunk_id": chunk.id,
            "reason": reason,
        }

    def _score_chunk(self, chunk: DocumentChunk, document: Document, terms: list[str]) -> int:
        haystack = "\n".join([document.title or "", document.department or "", chunk.section_title or "", chunk.content or ""]).lower()
        score = 0
        for term in terms:
            if term.lower() in haystack:
                score += 3
        if chunk.section_title:
            score += 1
        if chunk.page_number:
            score += 1
        if document.effective_date:
            score += 1
        return score

    def _normalize_content(self, content: str | None) -> str:
        text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _content_fingerprint(self, content: str) -> str:
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        return hashlib.sha256(normalized[:4000].encode("utf-8")).hexdigest()[:24]

    def _detect_sensitivity(self, content: str) -> str:
        lowered = content.lower()
        hits = sum(1 for term in SENSITIVE_TERMS if term.lower() in lowered)
        if hits >= 2:
            return "high"
        if hits == 1:
            return "medium"
        return "low"

    def _classify_doc_type(self, document: Document, chunk: DocumentChunk) -> str:
        haystack = " ".join(
            part for part in [document.title or "", document.file_name or "", document.file_type or "", chunk.section_title or "", document.department or ""] if part
        ).lower()
        for category, keywords in DOC_TYPE_RULES:
            if any(keyword.lower() in haystack for keyword in keywords):
                return category
        return "general"

    def _build_cpt_text(self, title: str, section_title: str | None, page_number: int | None, content: str) -> str:
        header = [f"文档标题：{title}"]
        if section_title:
            header.append(f"章节：{section_title}")
        if page_number:
            header.append(f"页码：{page_number}")
        return "\n".join(header) + "\n\n" + content

    def _build_sft_prompt(self, title: str, section_title: str | None, page_number: int | None, content: str) -> str:
        location = []
        if section_title:
            location.append(f"章节：{section_title}")
        if page_number:
            location.append(f"页码：{page_number}")
        location_line = "；".join(location) if location else "位置：未标注"
        return f"请根据以下企业管理文档片段，提炼 3 条管理要点，并指出一个执行风险。\n文档：{title}\n{location_line}\n\n{content}"

    def _build_rule_summary(self, content: str) -> str:
        sentences = [item.strip(" \n\t；。") for item in re.split(r"[。；;\n]+", content) if item.strip()]
        bullets = sentences[:3] if sentences else ["未提取到明确管理要点"]
        lines = [f"{index + 1}. {item}" for index, item in enumerate(bullets)]
        risk_source = sentences[3] if len(sentences) > 3 else (sentences[-1] if sentences else "原文信息不足")
        lines.append(f"执行风险：如未严格按上述要求执行，可能在“{risk_source[:36]}”相关环节出现审批遗漏、责任不清或留痕不足。")
        return "\n".join(lines)

    def _split_records(self, records: list[dict], *, train_ratio: float) -> tuple[list[dict], list[dict]]:
        bounded_ratio = min(max(train_ratio, 0.5), 0.98)
        shuffled = list(records)
        random.Random(42).shuffle(shuffled)
        train_cutoff = int(len(shuffled) * bounded_ratio)
        train_cutoff = min(max(train_cutoff, 1), max(len(shuffled) - 1, 1)) if len(shuffled) > 1 else len(shuffled)
        return shuffled[:train_cutoff], shuffled[train_cutoff:]

    def _write_jsonl(self, path: Path, rows: Iterable[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _count_excluded_reasons(self, rows: list[dict]) -> list[dict]:
        counts = Counter(item.get("reason", "unknown") for item in rows)
        return [{"reason": reason, "count": count} for reason, count in counts.most_common()]

    def _stub_document(self, record: dict, index: int):
        class StubDocument:
            pass

        stub = StubDocument()
        stub.id = str(record.get("doc_id") or record.get("source_path") or f"public-{index}")
        stub.title = str(record.get("title") or "未命名文档")
        stub.file_name = Path(str(record.get("source_path") or stub.id)).name
        stub.file_type = str(record.get("file_type") or "text/html")
        stub.department = str(record.get("department") or "public_cold_start")
        stub.access_level = 1
        stub.effective_date = None
        stub.updated_at = datetime.now(timezone.utc)
        return stub

    def _stub_chunk(self, record: dict, index: int, content: str):
        class StubChunk:
            pass

        stub = StubChunk()
        stub.id = f"chunk-{index}"
        stub.page_number = int(record.get("page_number") or 1)
        stub.section_title = str(record.get("section_title") or "")
        stub.content_type = str(record.get("content_type") or "text")
        stub.content = content
        stub.chunk_index = int(record.get("chunk_index") or index)
        return stub
