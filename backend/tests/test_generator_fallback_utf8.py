import pytest

from app.agent.nodes.generator import _build_rule_fallback
from app.security.output_guard import OutputGuard


def test_rule_fallback_returns_readable_structured_answer():
    answer = _build_rule_fallback(
        "请说明文档上传后是如何进入检索链路的。",
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

    assert "关于“请说明文档上传后是如何进入检索链路的。”的回答" in answer
    assert "文档上传后会先进入解析任务" in answer
    assert "引用依据" in answer
    assert "系统架构说明" in answer
    assert "鍙" not in answer


@pytest.mark.asyncio
async def test_output_guard_returns_clean_garbled_reason(monkeypatch):
    class DummySidecar:
        async def check_output(self, output):
            return {"safe": True, "mode": "sidecar"}

    guard = OutputGuard()
    guard.sidecar = DummySidecar()

    result = await guard.check("abc def ghi jkl mno pqr stu vwx yz")

    assert result["safe"] is False
    assert result["mode"] == "garbled_detection"
    assert "模型输出异常" in result["reason"]
    assert "鍙" not in result["reason"]
