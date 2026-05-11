import pytest

from app.agent.nodes.generator import _build_rule_fallback
from app.security.output_guard import OutputGuard

BAD_MOJIBAKE_MARKER = "\u9359"


def test_rule_fallback_returns_readable_structured_answer():
    answer = _build_rule_fallback(
        "请说明文档上传后是如何进入检索链路的？",
        [
            {
                "doc_id": "doc-1",
                "document_title": "系统架构说明",
                "page_number": 3,
                "section_title": "文档入库流程",
                "snippet": "文档上传后会先进入解析任务，随后执行切块、向量化和索引写入，完成后才能参与检索召回。",
                "score": 0.98,
            }
        ],
    )

    assert "关于“请说明文档上传后是如何进入检索链路的？”的回答" in answer
    assert "文档上传后会先进入解析任务" in answer
    assert "引用依据" in answer
    assert "系统架构说明" in answer
    assert BAD_MOJIBAKE_MARKER not in answer


def test_rule_fallback_supports_process_mode():
    answer = _build_rule_fallback(
        "差旅报销流程是什么？",
        [
            {
                "doc_id": "doc-1",
                "document_title": "差旅费管理办法",
                "page_number": 5,
                "section_title": "审批流程",
                "snippet": "出差人员应当先提交审批单，经部门负责人审核后报销。",
                "score": 0.98,
                "category": "process",
            }
        ],
        task_mode="process",
        evidence_pack={
            "salient_points": [
                {
                    "doc_id": "doc-1",
                    "document_title": "差旅费管理办法",
                    "page_number": 5,
                    "section_title": "审批流程",
                    "snippet": "出差人员应当先提交审批单，经部门负责人审核后报销。",
                    "score": 0.98,
                    "category": "process",
                }
            ]
        },
    )

    assert "流程结论" in answer
    assert "关键步骤" in answer
    assert "提交审批单" in answer


def test_rule_fallback_supports_extract_mode_with_fields():
    answer = _build_rule_fallback(
        "那需要哪些材料？",
        [
            {
                "doc_id": "doc-1",
                "document_title": "新进教职工合同签订常见问题",
                "page_number": 1,
                "section_title": "合同签订材料",
                "snippet": "有连续 1 年及以上正式工作经历的新进人员，须提供原单位聘用合同及社保缴纳证明。",
                "score": 0.99,
                "category": "requirements",
            }
        ],
        task_mode="extract",
        evidence_pack={
            "salient_points": [
                {
                    "doc_id": "doc-1",
                    "document_title": "新进教职工合同签订常见问题",
                    "page_number": 1,
                    "section_title": "合同签订材料",
                    "snippet": "有连续 1 年及以上正式工作经历的新进人员，须提供原单位聘用合同及社保缴纳证明。",
                    "score": 0.99,
                    "category": "requirements",
                }
            ]
        },
    )

    assert "提取字段" in answer
    assert "所需材料" in answer
    assert "聘用合同" in answer
    assert "社保缴纳证明" in answer
    assert "办理条件" in answer


@pytest.mark.asyncio
async def test_output_guard_returns_clean_garbled_reason():
    class DummySidecar:
        async def check_output(self, output):
            return {"safe": True, "mode": "sidecar"}

    guard = OutputGuard()
    guard.sidecar = DummySidecar()

    result = await guard.check("abc def ghi jkl mno pqr stu vwx yz")

    assert result["safe"] is False
    assert result["mode"] == "garbled_detection"
    assert "模型输出异常" in result["reason"]
    assert BAD_MOJIBAKE_MARKER not in result["reason"]
