from pathlib import Path

from app.services.public_corpus_service import PublicCorpusService


def test_extract_html_text_removes_boilerplate(tmp_path: Path):
    html = """<!doctype html>
    <html>
      <head><title>西南大学2024年度部门预算-信息公开</title></head>
      <body>
        <header>信息公开</header>
        <div id="vsb_content">
          <p>西南大学2024年度部门预算已经公开。</p>
          <p>预算安排坚持厉行节约。</p>
          <p>上一篇：无</p>
        </div>
        <footer>版权所有：西南大学</footer>
      </body>
    </html>"""
    path = tmp_path / "sample.html"
    path.write_text(html, encoding="utf-8")

    service = PublicCorpusService(tmp_path)
    text = service.extract_html_text(path)

    assert "信息公开" not in text
    assert "上一篇" not in text
    assert "预算安排坚持厉行节约" in text


def test_build_records_only_uses_html_sources(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    html_path = raw / "budget.html"
    html_path.write_text(
        "<html><head><title>预算公开</title></head><body><div id='vsb_content'>预算公开正文内容，包含预算管理办法。</div></body></html>",
        encoding="utf-8",
    )
    pdf_path = raw / "budget.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    (tmp_path / "sources.json").write_text(
        f"""[
  {{"title": "预算公开", "saved_path": "{html_path.as_posix()}"}},
  {{"title": "预算 PDF", "saved_path": "{pdf_path.as_posix()}"}}
]""",
        encoding="utf-8",
    )

    service = PublicCorpusService(tmp_path)
    records = service.build_records()

    assert len(records) == 1
    assert records[0]["title"] == "预算公开"
    assert "预算管理办法" in records[0]["content"]


def test_extract_attachment_records_uses_pdf_text(tmp_path: Path):
    html_path = tmp_path / "page.html"
    html_path.write_text(
        "<html><body><div id='vsb_content'><a href='/system/_content/download.jsp?id=1'>预算附件.pdf</a></div></body></html>",
        encoding="utf-8",
    )
    service = PublicCorpusService(tmp_path)

    fake_pdf = tmp_path / "attachment.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    service._download_attachment = lambda download_url, html_path, referer: fake_pdf  # type: ignore[method-assign]
    service.extract_pdf_text = lambda path: "预算公开正文内容，包含详细预算管理办法条款。"  # type: ignore[method-assign]

    records = service.extract_attachment_records({"title": "预算公开", "url": "https://xxgk.swu.edu.cn/info/1.htm"}, html_path)

    assert len(records) == 1
    assert records[0]["file_type"] == "application/pdf"
    assert "详细预算管理办法" in records[0]["content"]


def test_latest_export_summary_reads_latest_manifest(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    old_dir = reports_dir / "domain_tuning" / "public_cold_start" / "swu_public_docs_20260429_100000"
    new_dir = reports_dir / "domain_tuning" / "public_cold_start" / "swu_public_docs_20260429_110000"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "manifest.json").write_text('{"ok": true, "chunk_count": 10}', encoding="utf-8")
    (new_dir / "manifest.json").write_text('{"ok": true, "chunk_count": 12, "training_readiness": {"ready_for_sft": true}}', encoding="utf-8")

    service = PublicCorpusService(tmp_path)
    summary = service.latest_export_summary(reports_dir)

    assert summary["exists"] is True
    assert summary["chunk_count"] == 12
    assert summary["training_readiness"]["ready_for_sft"] is True
    assert summary["manifest_path"].endswith("manifest.json")
