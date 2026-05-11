from app.agent.nodes.retriever import _normalize_retrieved_results


class DummySearcher:
    @staticmethod
    def _extract_explicit_titles(_query: str):
        return []


def test_retriever_scopes_follow_up_results_to_previous_subject():
    results = [
        {
            "doc_id": "travel-doc",
            "document_title": "\u897f\u5357\u5927\u5b66\u56fd\u5185\u5dee\u65c5\u8d39\u7ba1\u7406\u529e\u6cd5\uff08\u4fee\u8ba2\uff09",
            "section_title": "\u62a5\u9500\u6750\u6599",
            "page_number": 4,
            "snippet": "\u5dee\u65c5\u62a5\u9500\u9700\u63d0\u4ea4\u5ba1\u6279\u5355\u3001\u884c\u7a0b\u5355\u548c\u7968\u636e\u3002",
            "score": 0.82,
        },
        {
            "doc_id": "hr-doc",
            "document_title": "\u897f\u5357\u5927\u5b66\u65b0\u8fdb\u6559\u804c\u5de5\u5408\u540c\u7b7e\u8ba2\u5e38\u89c1\u95ee\u9898",
            "section_title": "\u6750\u6599\u8981\u6c42",
            "page_number": 2,
            "snippet": "\u5408\u540c\u7b7e\u8ba2\u9700\u63d0\u4ea4\u8eab\u4efd\u8bc1\u3001\u5b66\u5386\u8bc1\u660e\u7b49\u6750\u6599\u3002",
            "score": 0.96,
        },
    ]

    normalized = _normalize_retrieved_results(
        DummySearcher(),
        query="\u90a3\u9700\u8981\u54ea\u4e9b\u6750\u6599\uff1f",
        results=results,
        plan={"max_per_doc": 2},
        conversation_state={
            "subject": "\u300a\u897f\u5357\u5927\u5b66\u56fd\u5185\u5dee\u65c5\u8d39\u7ba1\u7406\u529e\u6cd5\uff08\u4fee\u8ba2\uff09\u300b",
            "explicit_titles": ["\u300a\u897f\u5357\u5927\u5b66\u56fd\u5185\u5dee\u65c5\u8d39\u7ba1\u7406\u529e\u6cd5\uff08\u4fee\u8ba2\uff09\u300b"],
            "is_follow_up": True,
        },
    )

    assert normalized
    assert normalized[0]["doc_id"] == "travel-doc"
    assert all(item["doc_id"] != "hr-doc" for item in normalized)
