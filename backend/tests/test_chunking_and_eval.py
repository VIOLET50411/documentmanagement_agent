from pathlib import Path

import pytest

from app.config import settings
from app.evaluation.golden_dataset import GoldenDatasetGenerator
from app.evaluation.ragas_runner import RagasRunner
from app.evaluation.report_generator import ReportGenerator
from app.ingestion.chunking.parent_child_splitter import ParentChildSplitter
from app.ingestion.chunking.semantic_chunker import SemanticChunker
from app.ingestion.pipeline import DocumentIngestionPipeline
from app.ingestion.parsers.excel_parser import ExcelParser


def test_parent_child_splitter_creates_parent_and_children():
    splitter = ParentChildSplitter(parent_max_tokens=20, child_max_tokens=5, overlap=0.2)
    elements = [
        {"text": "差旅制度第一条：出差需要审批。 " * 4, "metadata": {"page_number": 1}},
        {"text": "报销材料包括发票和行程单。", "metadata": {"page_number": 1}},
    ]

    chunks = splitter.split(elements)

    assert any(chunk["is_parent"] for chunk in chunks)
    assert any(not chunk["is_parent"] for chunk in chunks)


def test_semantic_chunker_splits_chinese_sentences_without_mojibake_boundaries():
    chunker = SemanticChunker(max_tokens=20)

    parts = chunker._split_sentences("第一条：提交申请。第二条：经理审批！第三条：完成报销？")

    assert parts == ["第一条：提交申请。", "第二条：经理审批！", "第三条：完成报销？"]


def test_parent_child_splitter_prefers_semantic_chunks(monkeypatch):
    splitter = ParentChildSplitter(parent_max_tokens=200, child_max_tokens=3, overlap=0.2)
    monkeypatch.setattr(
        splitter.semantic_chunker,
        "chunk",
        lambda text: ["第一段 语义块", "第二段 语义块"],
    )

    chunks = splitter._split_text("第一段 语义块 第二段 语义块", 3)

    assert chunks == ["第一段 语义块", "第二段 语义块"]


def test_parent_child_splitter_preserves_sections_pages_and_parser():
    splitter = ParentChildSplitter(parent_max_tokens=128, child_max_tokens=16, overlap=0.1)
    elements = [
        {"type": "heading", "text": "第一章 总则", "metadata": {"page_number": 1, "section_title": "第一章 总则", "parser": "pypdf"}},
        {"type": "paragraph", "text": "出差前需要提交申请。", "metadata": {"page_number": 1, "section_title": "第一章 总则", "parser": "pypdf"}},
        {"type": "paragraph", "text": "审批完成后方可预订。", "metadata": {"page_number": 2, "section_title": "第一章 总则", "parser": "pypdf"}},
    ]

    chunks = splitter.split(elements)

    parents = [chunk for chunk in chunks if chunk["is_parent"]]
    children = [chunk for chunk in chunks if not chunk["is_parent"]]

    assert len(parents) == 2
    assert parents[0]["section_title"] == "第一章 总则"
    assert parents[0]["page_number"] == 1
    assert parents[0]["parser"] == "pypdf"
    assert "heading" in parents[0]["element_types"]
    assert children[0]["parent_id"] == parents[0]["id"]
    assert children[-1]["page_number"] == 2


def test_semantic_chunker_splits_long_cjk_text_without_spaces():
    chunker = SemanticChunker(max_tokens=10, overlap_ratio=0.2)

    chunks = chunker._split_oversized_text("预算审批流程需要先提交申请再由部门负责人审核最后财务复核生成凭证")

    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_pipeline_routes_image_files_to_ocr_parser():
    pipeline = DocumentIngestionPipeline()

    parser = pipeline._resolve_parser("image/png", "receipt.png")

    assert parser.__class__.__name__ == "OCRParser"


@pytest.mark.asyncio
async def test_golden_dataset_and_ragas_fallback(tmp_path: Path):
    original_base_url = settings.ragas_api_base_url
    original_require_real = settings.ragas_require_real_mode
    settings.ragas_api_base_url = ""
    settings.ragas_require_real_mode = False

    generator = GoldenDatasetGenerator()
    try:
        dataset = await generator.generate(
            [{"id": "doc-1", "title": "测试文档", "chunks": [{"content": "这是一个测试段落。"}]}],
            count=5,
        )

        assert dataset
        assert "测试文档" in dataset[0]["question"]
        assert dataset[0]["reference"] == dataset[0]["answer"]

        metrics = await RagasRunner().evaluate(dataset=dataset)
        assert metrics["sample_count"] >= 1

        report_path = ReportGenerator().generate_radar_chart(metrics, output_path=str(tmp_path / "report.md"))
        assert Path(report_path).exists()
    finally:
        settings.ragas_api_base_url = original_base_url
        settings.ragas_require_real_mode = original_require_real


@pytest.mark.asyncio
async def test_golden_dataset_builds_structured_pairs_from_markdown_table():
    generator = GoldenDatasetGenerator()

    dataset = await generator.generate(
        [
            {
                "id": "doc-table",
                "title": "预算表",
                "chunks": [
                    {
                        "content": "| policy | owner | amount |\n| --- | --- | --- |\n| 员工报销流程 | 财务部 | 5000 |\n| 差旅审批规则 | 行政部 | 3000 |"
                    }
                ],
            }
        ],
        count=5,
    )

    assert len(dataset) == 4
    assert dataset[0]["question"] == "员工报销流程的负责部门是什么？"
    assert dataset[0]["reference"] == dataset[0]["answer"]
    assert dataset[0]["answer"] == "财务部"
    assert dataset[1]["contexts"] == ["预算表中，员工报销流程：负责部门是财务部；金额是5000。"]


@pytest.mark.asyncio
async def test_golden_dataset_uses_clean_default_title_and_sentence_split():
    generator = GoldenDatasetGenerator()

    dataset = await generator.generate(
        [{"id": "doc-2", "chunks": [{"content": "第一条：提交申请。第二条：经理审批！第三条：完成报销？"}]}],
        count=3,
    )

    assert dataset
    assert "未命名文档" in dataset[0]["question"]
    assert dataset[0]["answer"] == "第一条：提交申请。"


@pytest.mark.asyncio
async def test_golden_dataset_deduplicates_identical_pairs():
    generator = GoldenDatasetGenerator()

    dataset = await generator.generate(
        [
            {
                "id": "doc-dup",
                "title": "重复预算表",
                "chunks": [
                    {
                        "content": "| policy | owner | amount |\n| --- | --- | --- |\n| 员工报销流程 | 财务部 | 5000 |\n| 员工报销流程 | 财务部 | 5000 |"
                    }
                ],
            }
        ],
        count=10,
    )

    assert len(dataset) == 2
    assert dataset[0]["question"] == "员工报销流程的负责部门是什么？"


def test_excel_parser_reads_gbk_csv_without_mojibake(tmp_path: Path):
    path = tmp_path / "policies.csv"
    path.write_bytes("policy,owner,amount\n员工报销流程,财务部,5000\n".encode("gb18030"))

    elements = ExcelParser().parse(str(path))

    assert elements
    assert "员工报销流程" in elements[0]["text"]
    assert "财务部" in elements[0]["text"]
