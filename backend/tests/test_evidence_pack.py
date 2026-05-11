from app.agent.nodes.evidence_pack import build_evidence_pack, classify_evidence


def test_build_evidence_pack_groups_points_and_detects_dominant_category():
    pack = build_evidence_pack(
        [
            {
                "doc_id": "doc-1",
                "document_title": "\u5dee\u65c5\u8d39\u7ba1\u7406\u529e\u6cd5",
                "section_title": "\u5ba1\u6279\u6d41\u7a0b",
                "page_number": 3,
                "snippet": "\u51fa\u5dee\u4eba\u5458\u5e94\u5f53\u5148\u63d0\u4ea4\u5ba1\u6279\u5355\uff0c\u7ecf\u90e8\u95e8\u8d1f\u8d23\u4eba\u5ba1\u6838\u540e\u62a5\u9500\u3002",
                "score": 0.95,
            },
            {
                "doc_id": "doc-1",
                "document_title": "\u5dee\u65c5\u8d39\u7ba1\u7406\u529e\u6cd5",
                "section_title": "\u62a5\u9500\u6807\u51c6",
                "page_number": 4,
                "snippet": "\u4f4f\u5bbf\u8d39\u6807\u51c6\u6309\u7167\u89c4\u5b9a\u9650\u989d\u6267\u884c\uff0c\u8d85\u51fa\u90e8\u5206\u4e2a\u4eba\u8d1f\u62c5\u3002",
                "score": 0.91,
            },
        ],
        query="\u5dee\u65c5\u62a5\u9500\u6d41\u7a0b\u662f\u4ec0\u4e48\uff1f",
    )

    assert pack["document_count"] == 1
    assert pack["dominant_category"] in {"process", "requirements"}
    assert pack["documents"][0]["doc_title"] == "\u5dee\u65c5\u8d39\u7ba1\u7406\u529e\u6cd5"
    assert len(pack["salient_points"]) == 2


def test_classify_evidence_marks_budget_table_as_numeric():
    category = classify_evidence(
        "\u897f\u5357\u5927\u5b66\u6536\u652f\u9884\u7b97\u603b\u8868 \u5355\u4f4d\uff1a\u4e07\u5143 \u8d22\u653f\u62e8\u6b3e\u6536\u5165 244,675.66 \u6559\u80b2\u652f\u51fa 452,738.18",
        query="2024\u5e74\u9884\u7b97\u91d1\u989d\u662f\u591a\u5c11\uff1f",
        section_title="\u90e8\u95e8\u9884\u7b97\u62a5\u8868",
    )
    assert category == "numeric"
