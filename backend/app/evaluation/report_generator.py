"""Generate evaluation reports in markdown format."""

from __future__ import annotations

import json
from pathlib import Path


class ReportGenerator:
    """Generate simple markdown and JSON evaluation reports."""

    def generate_radar_chart(self, metrics: dict, output_path: str = "evaluation_report.md"):
        """Backward-compatible markdown metrics report."""
        return self.generate_markdown_report({"metrics": metrics}, output_path=output_path)

    def generate_markdown_report(self, payload: dict, output_path: str = "evaluation_report.md"):
        """Generate a markdown report from evaluation payload."""
        path = Path(output_path)
        metrics = payload.get("metrics", payload)
        gate = payload.get("gate") or {}
        generated_from = payload.get("generated_from") or {}
        lines = [
            "# DocMind Evaluation Report",
            "",
            f"- Gate status: {'PASS' if gate.get('passed') else 'FAIL'}",
            f"- Dataset size: {payload.get('dataset_size', metrics.get('sample_count', 0))}",
            f"- Tenant: {generated_from.get('tenant_id', '-')}",
            f"- Source documents: {generated_from.get('document_count', '-')}",
            "",
            "| Metric | Score |",
            "| --- | ---: |",
        ]
        for key, value in metrics.items():
            if key == "_meta":
                continue
            lines.append(f"| {key} | {value} |")
        if metrics.get("_meta"):
            lines.extend(
                [
                    "",
                    "## Meta",
                    "",
                    f"- real_mode: {metrics['_meta'].get('real_mode')}",
                    f"- mode: {metrics['_meta'].get('mode')}",
                ]
            )
        if gate:
            lines.extend(["", "## Gate Summary", ""])
            if gate.get("passed"):
                lines.append("- All configured thresholds passed.")
            else:
                for item in gate.get("failures", []):
                    lines.append(
                        f"- {item.get('metric')}: actual={item.get('actual')} threshold={item.get('threshold')} delta={item.get('delta')}"
                    )
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def generate_json_report(self, metrics: dict, output_path: str = "evaluation_report.json"):
        path = Path(output_path)
        path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
