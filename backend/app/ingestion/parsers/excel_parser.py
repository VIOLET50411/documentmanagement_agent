"""Excel/CSV parser with sheet-aware structured output."""

from __future__ import annotations

import csv
from pathlib import Path


class ExcelParser:
    """Parse CSV or spreadsheet files into structured markdown-like elements."""

    def parse(self, file_path: str) -> list[dict]:
        path = Path(file_path)
        if path.suffix.lower() == ".csv":
            return self._parse_csv(path)
        return self._parse_xlsx(path)

    def _parse_xlsx(self, path: Path) -> list[dict]:
        try:
            from openpyxl import load_workbook
        except ImportError:
            return self._parse_xlsx_with_pandas(path)

        workbook = load_workbook(filename=path, data_only=False, read_only=True)
        elements: list[dict] = []
        for sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]
            rows = self._extract_rows_from_sheet(worksheet)
            if not rows:
                continue
            elements.append(
                {
                    "type": "table",
                    "text": self._render_markdown_table(rows),
                    "metadata": {
                        "sheet": sheet_name,
                        "section_title": sheet_name,
                        "row_count": max(len(rows) - 1, 0),
                        "column_count": max((len(row) for row in rows), default=0),
                        "merged_ranges": [],
                        "parser": "openpyxl",
                    },
                }
            )
        return elements

    def _parse_xlsx_with_pandas(self, path: Path) -> list[dict]:
        try:
            import pandas as pd
        except ImportError:
            return [
                {
                    "type": "table",
                    "text": f"文件 {path.name} 需要 pandas/openpyxl 才能完成表格解析。",
                    "metadata": {"sheet": path.stem, "parser": "fallback"},
                }
            ]

        sheets = pd.read_excel(path, sheet_name=None)
        elements: list[dict] = []
        for sheet_name, frame in sheets.items():
            clean_frame = frame.fillna("")
            rows = [list(map(str, clean_frame.columns.tolist()))]
            rows.extend([list(map(str, row)) for row in clean_frame.values.tolist()[:500]])
            if len(rows) == 1 and not any(rows[0]):
                continue
            elements.append(
                {
                    "type": "table",
                    "text": self._render_markdown_table(rows),
                    "metadata": {
                        "sheet": sheet_name,
                        "section_title": sheet_name,
                        "row_count": len(rows) - 1,
                        "column_count": max((len(row) for row in rows), default=0),
                        "parser": "pandas",
                    },
                }
            )
        return elements

    def _parse_csv(self, path: Path) -> list[dict]:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as file:
            reader = csv.reader(file)
            rows = list(reader)

        if not rows:
            return []

        return [
            {
                "type": "table",
                "text": self._render_markdown_table(rows[:501]),
                "metadata": {
                    "sheet": path.stem,
                    "section_title": path.stem,
                    "row_count": max(len(rows) - 1, 0),
                    "column_count": max((len(row) for row in rows[:501]), default=0),
                    "parser": "csv",
                },
            }
        ]

    def _extract_rows_from_sheet(self, worksheet) -> list[list[str]]:
        rows: list[list[str]] = []
        for row_index, row in enumerate(worksheet.iter_rows(values_only=False), start=1):
            rendered_row = [self._cell_to_text(cell) for cell in row]
            if any(value for value in rendered_row):
                rows.append(rendered_row)
            if row_index >= 500:
                break
        return rows

    def _render_markdown_table(self, rows: list[list[str]]) -> str:
        normalized_rows = rows or [[]]
        width = max((len(row) for row in normalized_rows), default=0)
        header = (normalized_rows[0] + [""] * width)[:width]
        body = [((row or []) + [""] * width)[:width] for row in normalized_rows[1:]]
        rendered = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        for row in body:
            rendered.append("| " + " | ".join(row) + " |")
        return "\n".join(rendered)

    def _cell_to_text(self, cell) -> str:
        value = cell.value
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value)
