"""公开冷启动语料清洗与导出辅助服务。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import settings
from app.ingestion.parsers.pdf_parser import PDFParser


BOILERPLATE_PATTERNS = (
    "版权所有",
    "上一篇",
    "下一篇",
    "返回首页",
    "信息公开",
    "打印本页",
    "关闭窗口",
    "地址：",
    "邮编：",
    "电话：",
    "Email：",
)

CONTENT_SELECTORS = (
    "#vsb_content",
    "#zoom",
    ".v_news_content",
    ".wp_articlecontent",
    ".TRS_Editor",
    ".content",
    ".article",
    "article",
    "main",
)


@dataclass
class PublicCorpusRecord:
    title: str
    content: str
    source_path: str
    file_type: str
    content_type: str = "text"
    section_title: str = ""
    page_number: int = 1
    department: str = "public_cold_start"
    score: int = 1


class PublicCorpusService:
    def __init__(self, dataset_root: str | Path):
        self.dataset_root = Path(dataset_root)
        self.attachments_dir = self.dataset_root / "raw" / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_parser = PDFParser()

    def load_manifest(self, name: str = "sources.json") -> list[dict]:
        return json.loads((self.dataset_root / name).read_text(encoding="utf-8"))

    def build_records(self) -> list[dict]:
        manifest = self.load_manifest()
        records: list[dict] = []
        for item in manifest:
            path = self._resolve_saved_path(item)
            if not path.exists():
                continue
            suffix = path.suffix.lower()
            if suffix == ".html":
                text = self.extract_html_text(path)
                if text:
                    records.extend(
                        self._build_chunked_records(
                            title=str(item.get("title") or path.stem),
                            content=text,
                            source_path=str(path),
                            file_type="text/html",
                            section_title=self.extract_title(path),
                            department="swu_public_docs",
                        )
                    )
                records.extend(self.extract_attachment_records(item, path))
            elif suffix == ".pdf":
                text = self.extract_pdf_text(path)
                if not text:
                    continue
                records.extend(
                    self._build_chunked_records(
                        title=str(item.get("title") or path.stem),
                        content=text,
                        source_path=str(path),
                        file_type="application/pdf",
                        section_title=str(item.get("title") or path.stem),
                        department="swu_public_docs",
                    )
                )
        return records

    def latest_export_summary(self, reports_dir: str | Path, tenant_id: str = "public_cold_start") -> dict:
        base_dir = Path(reports_dir) / "domain_tuning" / tenant_id
        if not base_dir.exists():
            return {"exists": False, "tenant_id": tenant_id, "base_dir": str(base_dir)}

        manifests = sorted(
            base_dir.glob("**/manifest.json"),
            key=lambda item: (item.stat().st_mtime, item.parent.name),
            reverse=True,
        )
        if not manifests:
            return {"exists": False, "tenant_id": tenant_id, "base_dir": str(base_dir)}

        manifest_path = manifests[0]
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "exists": False,
                "tenant_id": tenant_id,
                "base_dir": str(base_dir),
                "manifest_path": str(manifest_path),
                "error": "manifest_invalid_json",
            }

        payload["exists"] = True
        payload["manifest_path"] = str(manifest_path)
        payload["export_dir"] = str(manifest_path.parent)
        payload.setdefault("tenant_id", tenant_id)
        payload.setdefault("source_label", manifest_path.parent.name)
        return payload

    def _resolve_saved_path(self, item: dict) -> Path:
        saved_path = Path(str(item.get("saved_path") or ""))
        if saved_path.exists():
            return saved_path
        filename = str(item.get("filename") or saved_path.name or "")
        return self.dataset_root / "raw" / filename

    def extract_title(self, path: Path) -> str:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else path.stem
        return self.normalize_text(title)

    def extract_html_text(self, path: Path) -> str:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
        for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()

        container = None
        for selector in CONTENT_SELECTORS:
            container = soup.select_one(selector)
            if container is not None:
                break
        container = container or soup.body or soup

        for tag in container.select("nav, footer, header, aside, form"):
            tag.decompose()

        text = container.get_text("\n", strip=True)
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = self.normalize_text(raw_line)
            if len(line) < 8:
                continue
            if any(pattern in line for pattern in BOILERPLATE_PATTERNS):
                continue
            if re.fullmatch(r"[0-9/: \-]+", line):
                continue
            lines.append(line)

        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)

        text = "\n".join(deduped)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def extract_attachment_records(self, item: dict, html_path: Path) -> list[dict]:
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "lxml")
        page_url = str(item.get("url") or "")
        records: list[dict] = []
        seen_urls: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            label = self.normalize_text(anchor.get_text(" ", strip=True))
            if ".pdf" not in href.lower() and "download.jsp" not in href.lower() and ".pdf" not in label.lower():
                continue
            download_url = urljoin(page_url, href)
            if download_url in seen_urls:
                continue
            seen_urls.add(download_url)
            local_path = self._download_attachment(download_url, html_path, page_url)
            if local_path is None:
                continue
            text = self.extract_pdf_text(local_path)
            if not text:
                continue
            records.extend(
                self._build_chunked_records(
                    title=label or str(item.get("title") or local_path.stem),
                    content=text,
                    source_path=str(local_path),
                    file_type="application/pdf",
                    section_title=label or local_path.stem,
                    department="swu_public_docs",
                    score_bonus=2,
                )
            )
        return records

    def _download_attachment(self, download_url: str, html_path: Path, referer: str) -> Path | None:
        safe_name = f"{html_path.stem}__{Path(download_url.split('?')[0]).name or 'attachment.pdf'}"
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"
        target = self.attachments_dir / safe_name
        if target.exists() and target.stat().st_size > 100:
            return target

        response = requests.get(
            download_url,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": referer,
            },
        )
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            return None
        target.write_bytes(response.content)
        return target

    def extract_pdf_text(self, path: Path) -> str:
        try:
            elements = self.pdf_parser.parse(str(path))
        except Exception:  # noqa: BLE001
            return ""
        parts = [self.normalize_text(str(item.get("text") or "")) for item in elements if str(item.get("text") or "").strip()]
        parts = [item for item in parts if len(item) >= 8 and "暂时无法提取可用文本" not in item]
        text = "\n".join(parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def normalize_text(self, text: str) -> str:
        text = text.replace("\xa0", " ")
        text = text.replace("\u3000", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        return text.strip()

    def score_record(self, title: str, content: str) -> int:
        haystack = f"{title}\n{content}"
        score = 1
        for term in ("预算", "决算", "差旅", "科研", "资金", "管理办法", "实施办法", "制度"):
            if term in haystack:
                score += 2
        if len(content) >= settings.llm_enterprise_corpus_min_chars:
            score += 2
        return score

    def _build_chunked_records(
        self,
        *,
        title: str,
        content: str,
        source_path: str,
        file_type: str,
        section_title: str,
        department: str,
        score_bonus: int = 0,
    ) -> list[dict]:
        chunks = self._split_content(content)
        records: list[dict] = []
        for index, chunk in enumerate(chunks, start=1):
            score = self.score_record(title, chunk) + score_bonus
            records.append(
                PublicCorpusRecord(
                    title=title,
                    content=chunk,
                    source_path=source_path,
                    file_type=file_type,
                    section_title=section_title,
                    department=department,
                    page_number=index,
                    score=score,
                ).__dict__
            )
        return records

    def _split_content(self, content: str, *, max_chars: int = 1400, min_chars: int = 180) -> list[str]:
        paragraphs = [item.strip() for item in re.split(r"\n{2,}", content) if item.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [item.strip() for item in re.split(r"\n+", content) if item.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [item.strip() for item in re.split(r"(?<=[。；;])", content) if item.strip()]
        if not paragraphs:
            return [content]

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for paragraph in paragraphs:
            if current and current_len + len(paragraph) + 2 > max_chars:
                merged = "\n\n".join(current).strip()
                if len(merged) >= min_chars:
                    chunks.append(merged)
                current = [paragraph]
                current_len = len(paragraph)
            else:
                current.append(paragraph)
                current_len += len(paragraph) + 2
        if current:
            merged = "\n\n".join(current).strip()
            if len(merged) >= min_chars:
                chunks.append(merged)

        return chunks or [content.strip()]
