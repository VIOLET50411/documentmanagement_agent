"""PPTX parser with python-pptx support and XML fallback."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

PPTX_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PPTX_SLIDE_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
RELS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class PptxParser:
    """Parse PPTX files into heading, paragraph, and table elements."""

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)

        try:
            elements = self._parse_with_python_pptx(path)
            if elements:
                return elements
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            pass

        return self._parse_with_xml(path)

    def _parse_with_python_pptx(self, path: Path) -> list[dict]:
        try:
            from pptx import Presentation
            from pptx.util import Inches  # noqa: F401 — confirms pptx is importable
        except ImportError:
            return []

        prs = Presentation(str(path))
        elements: list[dict] = []

        for slide_index, slide in enumerate(prs.slides, start=1):
            slide_title = self._extract_slide_title(slide, slide_index)

            for shape_index, shape in enumerate(slide.shapes, start=1):
                # Tables
                if shape.has_table:
                    rows = self._extract_table_rows_pptx(shape.table)
                    if rows:
                        elements.append({
                            "type": "table",
                            "text": self._render_markdown_table(rows),
                            "metadata": {
                                "section_title": slide_title,
                                "page_number": slide_index,
                                "block_index": shape_index,
                                "parser": "python-pptx",
                            },
                        })
                    continue

                # Text frames
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = (para.text or "").strip()
                        if not text:
                            continue
                        # Detect headings by font size or level
                        is_heading = para.level == 0 and hasattr(para, 'font') and (
                            (para.font and para.font.size and para.font.size.pt >= 20)
                            if para.font else False
                        )
                        element_type = "heading" if is_heading else "paragraph"
                        elements.append({
                            "type": element_type,
                            "text": text,
                            "metadata": {
                                "section_title": slide_title,
                                "page_number": slide_index,
                                "block_index": shape_index,
                                "parser": "python-pptx",
                            },
                        })

        return elements

    def _extract_slide_title(self, slide, slide_index: int) -> str:
        """Try to extract the title shape text."""
        if slide.shapes.title and slide.shapes.title.text:
            return slide.shapes.title.text.strip()
        # Fallback: look for any shape with 'title' in its name
        for shape in slide.shapes:
            if hasattr(shape, "name") and "title" in (shape.name or "").lower():
                if shape.has_text_frame and shape.text_frame.text.strip():
                    return shape.text_frame.text.strip()
        return f"幻灯片 {slide_index}"

    def _extract_table_rows_pptx(self, table) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            if any(cells):
                rows.append(cells)
        return rows

    def _parse_with_xml(self, path: Path) -> list[dict]:
        """Fallback: parse PPTX as a ZIP of XML files."""
        elements: list[dict] = []

        with ZipFile(path) as archive:
            slide_names = sorted(
                [n for n in archive.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                key=lambda n: int("".join(filter(str.isdigit, n.split("/")[-1])) or 0),
            )

            for slide_index, slide_name in enumerate(slide_names, start=1):
                slide_title = f"幻灯片 {slide_index}"
                xml_bytes = archive.read(slide_name)
                root = ElementTree.fromstring(xml_bytes)
                ns = {"a": PPTX_NS, "p": PPTX_SLIDE_NS}

                # Extract all text paragraphs
                texts: list[str] = []
                for paragraph in root.iter(f"{{{PPTX_NS}}}p"):
                    runs = paragraph.findall(f".//{{{PPTX_NS}}}r/{{{PPTX_NS}}}t")
                    text = "".join((r.text or "") for r in runs).strip()
                    if text:
                        texts.append(text)

                # First text is usually the title
                if texts:
                    slide_title = texts[0]
                    elements.append({
                        "type": "heading",
                        "text": texts[0],
                        "metadata": {
                            "section_title": slide_title,
                            "page_number": slide_index,
                            "block_index": 1,
                            "parser": "xml",
                        },
                    })
                    for bi, text in enumerate(texts[1:], start=2):
                        elements.append({
                            "type": "paragraph",
                            "text": text,
                            "metadata": {
                                "section_title": slide_title,
                                "page_number": slide_index,
                                "block_index": bi,
                                "parser": "xml",
                            },
                        })

                # Extract tables
                table_index = 0
                for table_node in root.iter(f"{{{PPTX_NS}}}tbl"):
                    rows = self._extract_table_rows_xml(table_node)
                    if rows:
                        table_index += 1
                        elements.append({
                            "type": "table",
                            "text": self._render_markdown_table(rows),
                            "metadata": {
                                "section_title": slide_title,
                                "page_number": slide_index,
                                "table_index": table_index,
                                "parser": "xml",
                            },
                        })

        return elements

    def _extract_table_rows_xml(self, table_node) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table_node.iter(f"{{{PPTX_NS}}}tr"):
            cells: list[str] = []
            for cell in row.iter(f"{{{PPTX_NS}}}tc"):
                runs = cell.iter(f"{{{PPTX_NS}}}t")
                cell_text = "".join((r.text or "") for r in runs).strip()
                cells.append(cell_text)
            if any(cells):
                rows.append(cells)
        return rows

    def _render_markdown_table(self, rows: list[list[str]]) -> str:
        if not rows:
            return ""
        header = rows[0]
        body = rows[1:]
        rendered = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * len(header)) + " |",
        ]
        for row in body[:200]:
            padded = row + [""] * max(0, len(header) - len(row))
            rendered.append("| " + " | ".join(padded[: len(header)]) + " |")
        return "\n".join(rendered)
