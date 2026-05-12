"""HTML parser with main-content extraction and local attachment promotion."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from app.ingestion.parsers.pdf_parser import PDFParser

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

REMOVABLE_TAGS = ("script", "style", "noscript", "iframe", "svg")
CONTAINER_REMOVABLE_SELECTORS = ("nav", "footer", "header", "aside", "form")

BOILERPLATE_PATTERNS = (
    "\u7248\u6743\u6240\u6709",
    "\u4e0a\u4e00\u7bc7",
    "\u4e0b\u4e00\u7bc7",
    "\u8fd4\u56de\u9996\u9875",
    "\u4fe1\u606f\u516c\u5f00",
    "\u6253\u5370\u672c\u9875",
    "\u5173\u95ed\u7a97\u53e3",
    "\u5730\u5740\uff1a",
    "\u90ae\u7f16\uff1a",
    "\u7535\u8bdd\uff1a",
    "\u4f20\u771f\uff1a",
    "Email\uff1a",
    "\u6d4f\u89c8\u6b21\u6570",
    "\u5f53\u524d\u4f4d\u7f6e\uff1a",
)

LOW_SIGNAL_PATTERNS = (
    r"^\u9644\u4ef6\u3010?.+\u3011?\u5df2\u4e0b\u8f7d\d+\u6b21$",
    r"^\u53d1\u5e03\u65f6\u95f4[:\uff1a]?\s*\d{4}-\d{2}-\d{2}",
    r"^[0-9/: \-]+$",
)


class HTMLParser:
    """Parse HTML documents into structured text elements."""

    def __init__(self) -> None:
        self.pdf_parser = PDFParser()

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        raw = self._read_html(path)
        if raw is None:
            return self._fallback_notice(path, "html_read_failed")

        soup = BeautifulSoup(raw, "lxml")
        attachment_elements = self._parse_local_attachment_pdf(path, soup)
        if attachment_elements:
            return attachment_elements

        text = self._extract_html_text(soup)
        if not text or len(text.strip()) < 12:
            return self._fallback_notice(path, "html_empty_content")

        blocks = self._split_blocks(text)
        if not blocks:
            return self._fallback_notice(path, "html_no_blocks")

        document_title = self._extract_document_title(soup, path)
        parsed: list[dict] = [
            {
                "type": "paragraph",
                "text": (
                    f"\u7f51\u9875\u6587\u6863\u300a{document_title}\u300b\u6982\u89c8\uff1a"
                    f"\u5171\u63d0\u53d6{len(blocks)}\u4e2a\u6b63\u6587\u5757\u3002"
                ),
                "metadata": {
                    "page_number": 1,
                    "section_title": document_title,
                    "block_index": 0,
                    "char_count": len(document_title),
                    "file_name": path.name,
                    "parser": "html_overview",
                },
            }
        ]
        for idx, block in enumerate(blocks, start=1):
            parsed.append(
                {
                    "type": self._infer_type(block),
                    "text": block,
                    "metadata": {
                        "page_number": 1,
                        "section_title": self._guess_section(block, document_title),
                        "block_index": idx,
                        "char_count": len(block),
                        "file_name": path.name,
                        "parser": "html",
                    },
                }
            )
        return parsed

    def _read_html(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                try:
                    return path.read_bytes().decode("gb18030")
                except (OSError, UnicodeDecodeError):
                    return None
        except OSError:
            return None

    def _extract_html_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(REMOVABLE_TAGS):
            tag.decompose()

        container = None
        for selector in CONTENT_SELECTORS:
            container = soup.select_one(selector)
            if container is not None:
                break
        container = container or soup.body or soup

        for tag in container.select(",".join(CONTAINER_REMOVABLE_SELECTORS)):
            tag.decompose()

        text = container.get_text("\n", strip=True)
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = self._normalize_text(raw_line)
            if len(line) < 8:
                continue
            if any(pattern in line for pattern in BOILERPLATE_PATTERNS):
                continue
            if any(re.fullmatch(pattern, line) for pattern in LOW_SIGNAL_PATTERNS):
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
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _parse_local_attachment_pdf(self, html_path: Path, soup: BeautifulSoup) -> list[dict]:
        attachment_candidates = self._collect_attachment_candidates(html_path, soup)
        for attachment_path in attachment_candidates:
            try:
                elements = self.pdf_parser.parse(str(attachment_path))
            except Exception:  # noqa: BLE001
                continue
            if not self._has_substantive_elements(elements):
                continue
            return [self._annotate_attachment_element(item, html_path, attachment_path) for item in elements]
        return []

    def _collect_attachment_candidates(self, html_path: Path, soup: BeautifulSoup) -> list[Path]:
        candidates: list[Path] = []
        seen: set[Path] = set()
        attachments_dir = html_path.parent / "attachments"
        html_stem = html_path.stem

        def add_candidate(candidate: Path) -> None:
            resolved = candidate.resolve()
            if resolved in seen or not resolved.exists() or resolved.suffix.lower() != ".pdf":
                return
            seen.add(resolved)
            candidates.append(resolved)

        if attachments_dir.exists():
            for match in sorted(attachments_dir.glob(f"{html_stem}__*.pdf")):
                add_candidate(match)

        for anchor in soup.find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            label = self._normalize_text(anchor.get_text(" ", strip=True))
            if not self._looks_like_pdf_link(href, label):
                continue
            for candidate in self._resolve_local_attachment_paths(html_path, href):
                add_candidate(candidate)

        return candidates

    def _resolve_local_attachment_paths(self, html_path: Path, href: str) -> list[Path]:
        parsed = urlparse(href)
        href_path = unquote(parsed.path or "")
        basename = Path(href_path).name
        attachments_dir = html_path.parent / "attachments"
        html_stem = html_path.stem
        candidates: list[Path] = []

        if basename:
            candidates.append(html_path.parent / basename)
            candidates.append(attachments_dir / basename)
            candidates.append(attachments_dir / f"{html_stem}__{basename}")

        if parsed.query or "download.jsp" in href_path.lower():
            candidates.extend(sorted(attachments_dir.glob(f"{html_stem}__*.pdf")))

        return candidates

    def _looks_like_pdf_link(self, href: str, label: str) -> bool:
        href_lower = href.lower()
        label_lower = label.lower()
        return (
            ".pdf" in href_lower
            or ".pdf" in label_lower
            or "download.jsp" in href_lower
            or "downloadattachurl" in href_lower
        )

    def _has_substantive_elements(self, elements: list[dict]) -> bool:
        for item in elements:
            metadata = item.get("metadata") or {}
            text = self._normalize_text(str(item.get("text") or ""))
            if metadata.get("parser") in {"fallback", "html_fallback"}:
                continue
            if "\u6682\u65f6\u65e0\u6cd5\u63d0\u53d6\u53ef\u7528\u6587\u672c" in text:
                continue
            if "\u5f85 OCR \u6216\u4eba\u5de5\u590d\u6838" in text:
                continue
            if len(text) >= 20:
                return True
        return False

    def _annotate_attachment_element(self, item: dict, html_path: Path, attachment_path: Path) -> dict:
        metadata = dict(item.get("metadata") or {})
        metadata["parser"] = "html_attachment_pdf"
        metadata["source_html"] = html_path.name
        metadata["attachment_file_name"] = attachment_path.name
        metadata.setdefault("file_name", attachment_path.name)
        metadata["section_title"] = self._resolve_attachment_section_title(
            text=str(item.get("text") or ""),
            current_title=metadata.get("section_title"),
            html_path=html_path,
            attachment_path=attachment_path,
        )
        return {
            "type": item.get("type") or "paragraph",
            "text": str(item.get("text") or ""),
            "metadata": metadata,
        }

    def _resolve_attachment_section_title(
        self,
        *,
        text: str,
        current_title: str | None,
        html_path: Path,
        attachment_path: Path,
    ) -> str:
        normalized_current = self._normalize_text(str(current_title or ""))
        if normalized_current and "__download.jsp" not in normalized_current and normalized_current != attachment_path.stem:
            return normalized_current

        inferred = self._guess_attachment_heading(text)
        if inferred:
            return inferred

        html_title = self._normalize_attachment_label(html_path.stem)
        if html_title:
            return html_title

        return self._normalize_attachment_label(attachment_path.stem)

    def _guess_attachment_heading(self, text: str) -> str | None:
        normalized = self._normalize_text(text)
        if not normalized:
            return None
        normalized = re.sub(r"^\d+\s*", "", normalized)
        heading_match = re.match(
            (
                r"((?:[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+\u3001)?"
                r"[^\u3002\uff1b;]{2,40}?"
                r"(?:\u8bf4\u660e|\u60c5\u51b5\u8bf4\u660e|\u603b\u8868|\u76ee\u6807\u8868|\u6982\u51b5|\u76ee\u5f55))"
            ),
            normalized,
        )
        if heading_match:
            return heading_match.group(1).strip()

        first_line = re.split(r"[\u3002\uff01\uff1f\n]", normalized, maxsplit=1)[0].strip()
        if 4 <= len(first_line) <= 40:
            return first_line
        return None

    def _normalize_attachment_label(self, label: str) -> str:
        normalized = self._normalize_text(label)
        normalized = re.sub(r"__download\.jsp$", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"[_-]+", " ", normalized)
        return normalized.strip()

    def _extract_document_title(self, soup: BeautifulSoup, path: Path) -> str:
        heading = soup.select_one(".ct-title, .ch-title-2, h1, h2, title")
        title = heading.get_text(" ", strip=True) if heading is not None else path.stem
        title = self._normalize_text(title)
        return title or path.stem

    def _normalize_text(self, text: str) -> str:
        text = html.unescape(text)
        text = text.replace("\xa0", " ").replace("\u3000", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        return text.strip()

    def _split_blocks(self, text: str) -> list[str]:
        raw_blocks = re.split(r"\n{2,}", text)
        blocks: list[str] = []
        for block in raw_blocks:
            cleaned = re.sub(r"\n+", " ", block).strip()
            if len(cleaned) >= 8:
                blocks.append(cleaned)
        return blocks

    def _infer_type(self, text: str) -> str:
        compact = text.strip()
        if not compact:
            return "paragraph"
        if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9\-.、()（）《》“”：: ]{1,50}", compact):
            return "heading"
        if "|" in compact and compact.count("|") >= 2:
            return "table"
        return "paragraph"

    def _guess_section(self, text: str, fallback: str) -> str:
        first_line = re.split(r"[\u3002\uff01\uff1f\n]", text, maxsplit=1)[0].strip()
        if 2 <= len(first_line) <= 40:
            return first_line
        return fallback

    def _fallback_notice(self, path: Path, reason: str) -> list[dict]:
        return [
            {
                "type": "ocr_notice",
                "text": (
                    f"\u6587\u4ef6 {path.name} \u7684 HTML \u5185\u5bb9"
                    "\u6682\u65f6\u65e0\u6cd5\u63d0\u53d6\uff0c\u5df2\u6807\u8bb0\u4e3a\u5f85\u4eba\u5de5\u590d\u6838\u3002"
                ),
                "metadata": {
                    "page_number": 1,
                    "requires_ocr": False,
                    "parser": "html_fallback",
                    "reason": reason,
                    "file_name": path.name,
                },
            }
        ]
