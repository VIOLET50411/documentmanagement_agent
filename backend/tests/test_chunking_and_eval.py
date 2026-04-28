from pathlib import Path

import pytest

from app.config import settings
from app.evaluation.golden_dataset import GoldenDatasetGenerator
from app.evaluation.ragas_runner import RagasRunner
from app.evaluation.report_generator import ReportGenerator
from app.ingestion.chunking.parent_child_splitter import ParentChildSplitter
from app.ingestion.chunking.semantic_chunker import SemanticChunker


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

        metrics = await RagasRunner().evaluate(dataset=dataset)
        assert metrics["sample_count"] >= 1

        report_path = ReportGenerator().generate_radar_chart(metrics, output_path=str(tmp_path / "report.md"))
        assert Path(report_path).exists()
    finally:
        settings.ragas_api_base_url = original_base_url
        settings.ragas_require_real_mode = original_require_real
