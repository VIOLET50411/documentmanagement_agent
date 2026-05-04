from zipfile import ZipFile

from app.agent.agents.critic_agent import CriticAgent
from app.agent.agents.summary_agent import SummaryAgent
from app.agent.nodes.generator import generator
from app.agent.nodes.self_correction import self_correction
from app.ingestion.chunking.semantic_chunker import SemanticChunker
from app.ingestion.embedder import DocumentEmbedder
from app.ingestion.graph_extractor import GraphExtractor
from app.ingestion.metadata.tagger import MetadataTagger
from app.ingestion.parsers.docx_parser import DocxParser
from app.ingestion.parsers.excel_parser import ExcelParser
from app.ingestion.parsers.ocr_parser import OCRParser
from app.ingestion.parsers.pdf_parser import PDFParser
from app.retrieval.reranker import Reranker
from app.services.llm_service import LLMService


def test_semantic_chunker_splits_long_text():
    chunker = SemanticChunker(max_tokens=4)
    chunks = chunker.chunk("\u7b2c\u4e00\u53e5\u6d4b\u8bd5\u3002\u7b2c\u4e8c\u53e5\u6d4b\u8bd5\u3002\u7b2c\u4e09\u53e5\u6d4b\u8bd5\u3002")
    assert len(chunks) >= 2


def test_metadata_tagger_sets_fallback_fields():
    tagger = MetadataTagger()
    chunks = [{"content": "\u5dee\u65c5\u62a5\u9500\u9700\u8981\u9644\u53d1\u7968\u3002"}]
    tagged = tagger.tag(chunks, {"tenant_id": "t1", "doc_id": "d1", "file_name": "travel_policy.csv"})
    assert tagged[0]["department"] == "finance"
    assert tagged[0]["doc_type"] == "spreadsheet"
    assert tagged[0]["sensitivity_level"] == "medium"


def test_document_embedder_returns_dense_and_sparse():
    embedder = DocumentEmbedder()
    result = embedder.embed_query("\u5dee\u65c5\u62a5\u9500\u5ba1\u6279")
    assert len(result["dense"]) == embedder.dense_dim
    assert "\u5dee\u65c5\u62a5\u9500\u5ba1\u6279" in result["sparse"]


async def test_generator_builds_fallback_answer(monkeypatch):
    async def fake_generate(self, **kwargs):
        return None

    monkeypatch.setattr(LLMService, "generate", fake_generate)
    state = await generator(
        {
            "retrieved_docs": [
                {
                    "doc_id": "d1",
                    "document_title": "\u5dee\u65c5\u5236\u5ea6",
                    "section_title": "\u62a5\u9500\u89c4\u5219",
                    "snippet": "\u5dee\u65c5\u62a5\u9500\u9700\u8981\u9644\u53d1\u7968\u4e0e\u5ba1\u6279\u5355\u3002",
                    "page_number": 2,
                    "score": 1.0,
                }
            ]
        }
    )
    assert "\u68c0\u7d22\u7ed3\u679c" in state["answer"]
    assert state["citations"][0]["doc_title"] == "\u5dee\u65c5\u5236\u5ea6"


async def test_self_correction_marks_empty_results_insufficient():
    state = await self_correction({"query": "\u5e74\u5047\u5236\u5ea6", "retrieved_docs": []})
    assert state["retrieval_sufficient"] is False
    assert state["self_correction_reason"] == "no_results"


async def test_critic_blocks_uncited_specialist_answer():
    state = await CriticAgent().run({"answer": "\u6d4b\u8bd5\u7b54\u6848", "citations": [], "agent_used": "summary", "iteration": 0})
    assert state["critic_approved"] is False


async def test_summary_agent_returns_summary_text(monkeypatch):
    async def fake_generate(self, **kwargs):
        return None

    class DummyComplianceAgent:
        async def run(self, state):
            state["retrieved_docs"] = [
                {"document_title": "\u5458\u5de5\u624b\u518c", "section_title": "\u5e74\u5047\u5236\u5ea6", "snippet": "\u5458\u5de5\u8f6c\u6b63\u540e\u53ef\u7533\u8bf7\u5e74\u5047\u3002"}
            ]
            state["answer"] = ""
            state["citations"] = [{"doc_title": "\u5458\u5de5\u624b\u518c"}]
            return state

    from app.agent import agents as agents_pkg

    original = agents_pkg.summary_agent.ComplianceAgent
    monkeypatch.setattr(LLMService, "generate", fake_generate)
    agents_pkg.summary_agent.ComplianceAgent = DummyComplianceAgent
    try:
        state = await SummaryAgent().run({})
    finally:
        agents_pkg.summary_agent.ComplianceAgent = original
    assert "\u6587\u6863\u6458\u8981" in state["answer"]


async def test_graph_extractor_returns_relationships():
    extractor = GraphExtractor()
    triples = await extractor.extract_and_store(
        [{"doc_id": "d1", "section_title": "\u6d41\u7a0b", "content": "\u8d22\u52a1\u8d1f\u8d23\u5ba1\u6279\u5dee\u65c5\u62a5\u9500\u6d41\u7a0b\u3002"}]
    )
    assert triples
    assert triples[0]["relationship"] == "manages"


async def test_reranker_orders_by_overlap(monkeypatch):
    async def fake_generate(self, **kwargs):
        return None

    monkeypatch.setattr(LLMService, "generate", fake_generate)
    reranker = Reranker()
    ranked = await reranker.rerank(
        "\u5dee\u65c5 \u62a5\u9500",
        [
            {"document_title": "\u5458\u5de5\u624b\u518c", "section_title": "\u5e74\u5047", "snippet": "\u5e74\u5047\u6d41\u7a0b", "score": 0.1},
            {"document_title": "\u5dee\u65c5\u5236\u5ea6", "section_title": "\u62a5\u9500", "snippet": "\u5dee\u65c5\u62a5\u9500\u9700\u8981\u5ba1\u6279", "score": 0.1},
        ],
        top_k=1,
    )
    assert ranked[0]["document_title"] == "\u5dee\u65c5\u5236\u5ea6"


def test_ocr_parser_returns_notice():
    parser = OCRParser()
    result = parser.parse("scan.pdf")
    assert result[0]["metadata"]["requires_ocr"] is True
    assert result[0]["metadata"]["ocr_pending"] is True


def test_pdf_parser_returns_fallback_notice_for_unreadable_pdf(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"%PDF-1.4\\n%%EOF")
    result = PDFParser().parse(str(path))
    assert result[0]["metadata"]["requires_ocr"] is True
    assert result[0]["metadata"]["ocr_pending"] is True


def test_docx_parser_reads_heading_and_paragraph_from_xml(tmp_path):
    path = tmp_path / "sample.docx"
    document_xml = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
    <w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">
      <w:body>
        <w:p>
          <w:pPr><w:pStyle w:val=\"Heading1\" /></w:pPr>
          <w:r><w:t>\u5236\u5ea6\u6807\u9898</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>\u8fd9\u91cc\u662f\u6b63\u6587\u6bb5\u843d\u3002</w:t></w:r>
        </w:p>
      </w:body>
    </w:document>
    """
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    result = DocxParser().parse(str(path))
    assert result[0]["type"] == "heading"
    assert result[0]["text"] == "\u5236\u5ea6\u6807\u9898"
    assert result[1]["metadata"]["section_title"] == "\u5236\u5ea6\u6807\u9898"


def test_excel_parser_reads_csv_as_table(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text(
        "\u59d3\u540d,\u90e8\u95e8\n"
        "\u5f20\u4e09,\u8d22\u52a1\n"
        "\u674e\u56db,\u4eba\u4e8b\n",
        encoding="utf-8",
    )
    result = ExcelParser().parse(str(path))
    assert result[0]["type"] == "table"
    assert "\u5f20\u4e09" in result[0]["text"]
    assert result[0]["metadata"]["row_count"] == 2
