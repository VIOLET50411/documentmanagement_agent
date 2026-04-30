from app.services.enterprise_tuning_service import EnterpriseTuningService


def test_content_fingerprint_is_stable_for_whitespace_changes():
    service = EnterpriseTuningService(db=None, reports_dir="reports")
    left = service._content_fingerprint("审批 流程 规范\n\n第一条")
    right = service._content_fingerprint("审批   流程 规范 第一条")
    assert left == right


def test_detect_sensitivity_levels():
    service = EnterpriseTuningService(db=None, reports_dir="reports")
    assert service._detect_sensitivity("差旅制度说明") == "low"
    assert service._detect_sensitivity("联系人手机号请保密") == "medium"
    assert service._detect_sensitivity("员工手机号与身份证信息严禁外泄") == "high"


def test_classify_doc_type_by_title_and_section():
    service = EnterpriseTuningService(db=None, reports_dir="reports")

    class DocumentStub:
        title = "采购审批管理办法"
        file_name = "采购审批管理办法.docx"
        file_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        department = "采购部"

    class ChunkStub:
        section_title = "审批流程"

    assert service._classify_doc_type(DocumentStub(), ChunkStub()) == "policy"


def test_split_records_keeps_train_and_val():
    service = EnterpriseTuningService(db=None, reports_dir="reports")
    rows = [{"id": str(index)} for index in range(10)]
    train, val = service._split_records(rows, train_ratio=0.8)
    assert len(train) == 8
    assert len(val) == 2
