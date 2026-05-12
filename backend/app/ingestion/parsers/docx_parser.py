"""DOCX parser with optional python-docx support and XML fallback."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class DocxParser:
    """Parse DOCX files into heading, paragraph, and table elements."""

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)

        try:
            elements = self._parse_with_python_docx(path)
            if elements:
                return elements
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            pass

        return self._parse_with_xml(path)

    def _parse_with_python_docx(self, path: Path) -> list[dict]:
        try:
            from docx import Document
            from docx.oxml.table import CT_Tbl
            from docx.oxml.text.paragraph import CT_P
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError:
            return []

        document = Document(str(path))
        elements: list[dict] = []
        current_heading = path.stem
        table_index = 0

        for block_index, child in enumerate(document.element.body.iterchildren(), start=1):
            if isinstance(child, CT_P):
                paragraph = Paragraph(child, document)
                text = (paragraph.text or "").strip()
                if not text:
                    continue
                style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
                element_type = "heading" if "heading" in style_name or "title" in style_name else "paragraph"
                if element_type == "heading":
                    current_heading = text
                elements.append(
                    {
                        "type": element_type,
                        "text": text,
                        "metadata": {
                            "section_title": current_heading,
                            "block_index": block_index,
                            "parser": "python-docx",
                        },
                    }
                )
            elif isinstance(child, CT_Tbl):
                table = Table(child, document)
                rows = self._extract_table_rows(table.rows)
                if not rows:
                    continue
                table_index += 1
                elements.append(self._build_table_summary_element(rows=rows, section_title=current_heading, block_index=block_index, parser="python-docx"))
                elements.append(
                    {
                        "type": "table",
                        "text": self._render_markdown_table(rows),
                        "metadata": {
                            "section_title": current_heading,
                            "block_index": block_index,
                            "table_index": table_index,
                            "parser": "python-docx",
                        },
                    }
                )
        if not elements:
            return elements
        return [
            {
                "type": "paragraph",
                "text": f"文档《{path.stem}》概览：包含{sum(1 for item in elements if item['type'] in {'heading', 'paragraph'})}段正文、{sum(1 for item in elements if item['type'] == 'table')}个表格。",
                "metadata": {
                    "section_title": path.stem,
                    "block_index": 0,
                    "parser": "docx_overview",
                },
            },
            *elements,
        ]

    def _parse_with_xml(self, path: Path) -> list[dict]:
        with ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")

        root = ElementTree.fromstring(xml_bytes)
        namespace = {"w": WORD_NS}
        elements: list[dict] = []
        current_heading = path.stem
        body = root.find(".//w:body", namespace)
        if body is None:
            return []

        table_index = 0
        for block_index, child in enumerate(list(body), start=1):
            if child.tag == self._w_tag("p"):
                text = self._extract_paragraph_text_xml(child, namespace)
                if not text:
                    continue
                style = child.find("./w:pPr/w:pStyle", namespace)
                style_value = (style.attrib.get(self._w_tag("val"), "") if style is not None else "").lower()
                element_type = "heading" if style_value.startswith("heading") or style_value == "title" else "paragraph"
                if element_type == "heading":
                    current_heading = text
                elements.append(
                    {
                        "type": element_type,
                        "text": text,
                        "metadata": {
                            "section_title": current_heading,
                            "block_index": block_index,
                            "parser": "xml",
                        },
                    }
                )
            elif child.tag == self._w_tag("tbl"):
                rows = self._extract_table_rows_xml(child, namespace)
                if not rows:
                    continue
                table_index += 1
                elements.append(self._build_table_summary_element(rows=rows, section_title=current_heading, block_index=block_index, parser="xml"))
                elements.append(
                    {
                        "type": "table",
                        "text": self._render_markdown_table(rows),
                        "metadata": {
                            "section_title": current_heading,
                            "block_index": block_index,
                            "table_index": table_index,
                            "parser": "xml",
                        },
                    }
                )

        return elements

    def _extract_table_rows(self, rows) -> list[list[str]]:
        extracted: list[list[str]] = []
        for row in rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            if any(cells):
                extracted.append(cells)
        return extracted

    def _extract_paragraph_text_xml(self, paragraph, namespace: dict[str, str]) -> str:
        text_parts = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
        return "".join(text_parts).strip()

    def _extract_table_rows_xml(self, table, namespace: dict[str, str]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.findall(".//w:tr", namespace):
            cells = []
            for cell in row.findall("./w:tc", namespace):
                cell_text = "".join(node.text for node in cell.findall(".//w:t", namespace) if node.text).strip()
                cells.append(cell_text)
            if any(cells):
                rows.append(cells)
        return rows

    def _w_tag(self, name: str) -> str:
        return f"{{{WORD_NS}}}{name}"

    def _render_markdown_table(self, rows: list[list[str]]) -> str:
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

    def _build_table_summary_element(
        self,
        *,
        rows: list[list[str]],
        section_title: str,
        block_index: int,
        parser: str,
    ) -> dict:
        headers = [cell for cell in rows[0] if cell][:5]
        row_count = max(len(rows) - 1, 0)
        header_text = "、".join(headers) if headers else "未识别列名"
        return {
            "type": "paragraph",
            "text": f"表格摘要：共{row_count}行，字段包括{header_text}。",
            "metadata": {
                "section_title": section_title,
                "block_index": block_index,
                "parser": f"{parser}_table_summary",
            },
        }
