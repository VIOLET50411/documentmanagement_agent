import pytest

from app.retrieval.reranker import Reranker


@pytest.mark.asyncio
async def test_reranker_prefers_title_and_exact_match():
    reranker = Reranker()
    ranked = await reranker.rerank(
        "\u5dee\u65c5\u62a5\u9500\u5236\u5ea6",
        [
            {"document_title": "\u5458\u5de5\u624b\u518c", "section_title": "\u5e74\u5047", "snippet": "\u5e74\u5047\u6d41\u7a0b", "score": 0.8},
            {"document_title": "\u5dee\u65c5\u62a5\u9500\u5236\u5ea6", "section_title": "\u62a5\u9500\u8981\u6c42", "snippet": "\u5dee\u65c5\u62a5\u9500\u5236\u5ea6\u8981\u6c42\u53d1\u7968\u548c\u5ba1\u6279\u5355", "score": 0.4},
        ],
        top_k=1,
    )
    assert ranked[0]["document_title"] == "\u5dee\u65c5\u62a5\u9500\u5236\u5ea6"


@pytest.mark.asyncio
async def test_reranker_adds_department_and_freshness_boost():
    reranker = Reranker()
    ranked = await reranker.rerank(
        "\u8d22\u52a1\u62a5\u9500\u89c4\u8303",
        [
            {
                "document_title": "\u901a\u7528\u5236\u5ea6",
                "section_title": "\u516c\u544a",
                "snippet": "\u516c\u53f8\u901a\u77e5",
                "score": 1.0,
                "department": "public",
                "updated_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "document_title": "\u8d22\u52a1\u62a5\u9500\u89c4\u8303",
                "section_title": "\u62a5\u9500\u5ba1\u6279",
                "snippet": "\u8d22\u52a1\u90e8\u95e8\u8d1f\u8d23\u62a5\u9500\u5ba1\u6279",
                "score": 0.4,
                "department": "finance",
                "updated_at": "2099-01-01T00:00:00+00:00",
            },
        ],
        top_k=2,
    )
    assert ranked[0]["department"] == "finance"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]


@pytest.mark.asyncio
async def test_reranker_prefers_explicit_document_title_lookup():
    reranker = Reranker()
    ranked = await reranker.rerank(
        "请根据《西南大学新进教职工合同签订常见问题》概括试用期规则",
        [
            {
                "document_title": "员工手册",
                "section_title": "试用期",
                "snippet": "员工试用期按岗位安排执行。",
                "score": 1.2,
            },
            {
                "document_title": "西南大学新进教职工合同签订常见问题.pdf",
                "section_title": "试用期",
                "snippet": "签订合同时，部分新进人员需约定试用期，试用期为12个月。",
                "score": 0.5,
            },
        ],
        top_k=2,
    )

    assert ranked[0]["document_title"] == "西南大学新进教职工合同签订常见问题.pdf"
