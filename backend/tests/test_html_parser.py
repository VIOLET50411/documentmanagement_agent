from pathlib import Path

from app.ingestion.parsers.html_parser import HTMLParser


def test_html_parser_promotes_local_attachment_pdf(tmp_path, monkeypatch):
    html_path = tmp_path / "notice.html"
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir()
    attachment_path = attachments_dir / "notice__download.jsp.pdf"
    attachment_path.write_bytes(b"%PDF-1.4 fake")
    html_path.write_text(
        """
        <html>
          <body>
            <div id="vsb_content">
              <p><a href="/system/_content/download.jsp?id=1">通知正文.pdf</a></p>
            </div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    parser = HTMLParser()

    def fake_parse(file_path: str):
        assert Path(file_path).name == "notice__download.jsp.pdf"
        return [
            {
                "type": "paragraph",
                "text": "这是附件 PDF 的真实正文内容，包含预算说明和执行要求。",
                "metadata": {"page_number": 2, "parser": "pypdf", "section_title": "正文"},
            }
        ]

    monkeypatch.setattr(parser.pdf_parser, "parse", fake_parse)

    elements = parser.parse(str(html_path))

    assert len(elements) == 1
    assert elements[0]["text"].startswith("这是附件 PDF 的真实正文内容")
    assert elements[0]["metadata"]["parser"] == "html_attachment_pdf"
    assert elements[0]["metadata"]["source_html"] == "notice.html"
    assert elements[0]["metadata"]["attachment_file_name"] == "notice__download.jsp.pdf"
    assert elements[0]["metadata"]["section_title"] == "正文"


def test_html_parser_falls_back_to_html_when_attachment_is_not_substantive(tmp_path, monkeypatch):
    html_path = tmp_path / "policy.html"
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir()
    attachment_path = attachments_dir / "policy__download.jsp.pdf"
    attachment_path.write_bytes(b"%PDF-1.4 fake")
    html_path.write_text(
        """
        <html>
          <body>
            <div class="ct-title"><div class="ch-title-2">出差管理办法</div></div>
            <div id="vsb_content">
              <p>出差申请应至少提前两个工作日提交审批。</p>
              <p><a href="/system/_content/download.jsp?id=2">附件下载</a></p>
            </div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    parser = HTMLParser()
    monkeypatch.setattr(
        parser.pdf_parser,
        "parse",
        lambda _file_path: [
            {
                "type": "ocr_notice",
                "text": "文件 policy__download.jsp.pdf 暂时无法提取可用文本，已标记为待 OCR 或人工复核。",
                "metadata": {"parser": "fallback"},
            }
        ],
    )

    elements = parser.parse(str(html_path))

    assert any("出差申请应至少提前两个工作日提交审批" in item["text"] for item in elements)
    assert all(item["metadata"]["parser"] == "html" for item in elements)


def test_html_parser_extracts_main_content_and_strips_boilerplate(tmp_path):
    html_path = tmp_path / "rules.html"
    html_path.write_text(
        """
        <html>
          <head><title>请假制度</title></head>
          <body>
            <header>信息公开</header>
            <div class="content">
              <div>当前位置：首页 &gt; 正文</div>
              <p>请假申请需由部门负责人审批后生效。</p>
              <p>请假结束后应及时销假并补全系统记录。</p>
              <p>打印本页</p>
              <p>地址：重庆市北碚区</p>
            </div>
            <footer>版权所有</footer>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    elements = HTMLParser().parse(str(html_path))
    joined = "\n".join(item["text"] for item in elements)

    assert "请假申请需由部门负责人审批后生效。" in joined
    assert "请假结束后应及时销假并补全系统记录。" in joined
    assert "打印本页" not in joined
    assert "地址：重庆市北碚区" not in joined
    assert "当前位置：首页" not in joined


def test_html_parser_rewrites_attachment_stem_to_natural_section_title(tmp_path, monkeypatch):
    html_path = tmp_path / "budget_notice.html"
    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir()
    attachment_path = attachments_dir / "budget_notice__download.jsp.pdf"
    attachment_path.write_bytes(b"%PDF-1.4 fake")
    html_path.write_text(
        """
        <html>
          <body>
            <div class="ct-title"><div class="ch-title-2">西南大学2023年度部门预算</div></div>
            <div id="vsb_content">
              <p><a href="/system/_content/download.jsp?id=1">西南大学2023年度部门预算.pdf</a></p>
            </div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    parser = HTMLParser()

    monkeypatch.setattr(
        parser.pdf_parser,
        "parse",
        lambda _file_path: [
            {
                "type": "paragraph",
                "text": "11 三、部门预算情况说明 （一）收支预算情况说明 我校2023年收支总预算557,259.13万元。",
                "metadata": {"page_number": 11, "parser": "pypdf", "section_title": "budget_notice__download.jsp"},
            }
        ],
    )

    elements = parser.parse(str(html_path))

    assert elements[0]["metadata"]["section_title"] == "三、部门预算情况说明"
