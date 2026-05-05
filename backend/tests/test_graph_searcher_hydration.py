from types import SimpleNamespace

import pytest

from app.retrieval.graph_searcher import GraphSearcher


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, *responses):
        self._responses = list(responses)

    async def execute(self, _stmt):
        if not self._responses:
            raise AssertionError("unexpected execute call")
        return _FakeRows(self._responses.pop(0))


@pytest.mark.asyncio
async def test_graph_searcher_hydrates_neo4j_results_with_document_metadata():
    searcher = GraphSearcher()
    db = _FakeDB(
        [
            SimpleNamespace(id="doc-1", title="差旅审批制度.pdf", department="finance"),
        ],
        [
            SimpleNamespace(
                doc_id="doc-1",
                id="chunk-1",
                content="差旅审批由部门负责人和财务复核共同完成。",
                page_number=2,
                section_title="审批流程",
                chunk_index=0,
            ),
        ],
    )

    hydrated = await searcher._hydrate_live_results(
        db=db,
        tenant_id="default",
        results=[
            {
                "doc_id": "doc-1",
                "chunk_id": None,
                "document_title": "doc-1",
                "snippet": "负责人 -> 审批流程",
                "page_number": None,
                "section_title": "审批流程",
                "relationship": "manages",
                "score": 1.0,
                "source_type": "neo4j",
            }
        ],
    )

    assert hydrated[0]["document_title"] == "差旅审批制度.pdf"
    assert hydrated[0]["chunk_id"] == "chunk-1"
    assert hydrated[0]["page_number"] == 2
    assert hydrated[0]["section_title"] == "审批流程"
    assert hydrated[0]["department"] == "finance"
    assert hydrated[0]["snippet"] == "差旅审批由部门负责人和财务复核共同完成。"
    assert hydrated[0]["graph_path"] == "负责人 -> 审批流程"


def test_graph_searcher_prefers_matching_section_chunk():
    searcher = GraphSearcher()

    chunk = searcher._pick_best_chunk(
        [
            {"chunk_id": "chunk-1", "section_title": "总则", "content": "总则内容"},
            {"chunk_id": "chunk-2", "section_title": "审批流程", "content": "审批流程内容"},
        ],
        "审批流程",
    )

    assert chunk["chunk_id"] == "chunk-2"


@pytest.mark.asyncio
async def test_graph_searcher_drops_unresolved_neo4j_results():
    searcher = GraphSearcher()
    db = _FakeDB([], [])

    hydrated = await searcher._hydrate_live_results(
        db=db,
        tenant_id="default",
        results=[
            {
                "doc_id": "d1",
                "chunk_id": None,
                "document_title": "d1",
                "snippet": "财务负责审批差旅报销流程 -> 流程",
                "page_number": None,
                "section_title": "流程",
                "relationship": "manages",
                "score": 1.0,
                "source_type": "neo4j",
            }
        ],
    )

    assert hydrated == []


def test_graph_searcher_dedupes_same_doc_section_and_snippet():
    searcher = GraphSearcher()

    deduped = searcher._dedupe_results(
        [
            {
                "doc_id": "doc-1",
                "chunk_id": "chunk-1",
                "document_title": "制度A",
                "section_title": "审批流程",
                "page_number": 3,
                "snippet": "审批流程内容相同",
                "score": 1.0,
                "source_type": "graph",
            },
            {
                "doc_id": "doc-1",
                "chunk_id": "chunk-2",
                "document_title": "制度A",
                "section_title": "审批流程",
                "page_number": 3,
                "snippet": "审批流程内容相同",
                "score": 0.9,
                "source_type": "graph",
            },
            {
                "doc_id": "doc-1",
                "chunk_id": "chunk-3",
                "document_title": "制度A",
                "section_title": "职责说明",
                "page_number": 4,
                "snippet": "另一段内容",
                "score": 0.8,
                "source_type": "graph",
            },
        ]
    )

    assert [item["chunk_id"] for item in deduped] == ["chunk-1", "chunk-3"]
