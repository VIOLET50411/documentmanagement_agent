from app.agent.agents.summary_agent import SummaryAgent


def test_summary_agent_prioritizes_overview_chunks_over_faq_detail():
    agent = SummaryAgent()
    docs = [
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题",
            "page_number": 1,
            "section_title": "常见问题解答",
            "snippet": "本问答主要围绕新进教职工合同签订、试用期、起薪、报到材料和相关办理要求进行说明。",
            "score": 0.82,
        },
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题",
            "page_number": 1,
            "section_title": "一、新进人员签订合同，哪些情况下签订有约定试用期的聘用合同？",
            "snippet": "新进人员签订合同，哪些情况下签订有约定试用期的聘用合同？",
            "score": 0.93,
        },
    ]

    ordered = agent._prioritize_summary_docs(docs)

    assert ordered[0]["section_title"] == "常见问题解答"


def test_summary_agent_builds_topic_level_lead_instead_of_copying_first_question():
    agent = SummaryAgent()
    docs = [
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题",
            "page_number": 1,
            "section_title": "常见问题解答",
            "snippet": "本问答主要围绕新进教职工合同签订、试用期、起薪、报到材料和相关办理要求进行说明。",
            "score": 0.92,
        },
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题",
            "page_number": 2,
            "section_title": "合同签订材料",
            "snippet": "有连续 1 年及以上正式工作经历的新进人员，须提供原单位聘用合同及社保缴纳证明。",
            "score": 0.88,
        },
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题",
            "page_number": 3,
            "section_title": "起薪与试用期",
            "snippet": "文档说明了不同入职情形下的起薪时间和试用期适用规则。",
            "score": 0.84,
        },
    ]

    answer = agent._build_structured_summary(agent._prioritize_summary_docs(docs))

    assert "主要围绕" in answer
    assert "合同签订" in answer
    assert "报到材料" in answer or "合同签订材料" in answer
    assert "哪些情况下" not in answer.split("**摘要结论：**", 1)[1].splitlines()[0]


def test_summary_agent_compacts_faq_chunks_into_brief_points():
    agent = SummaryAgent()
    docs = [
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题.pdf",
            "page_number": 1,
            "section_title": "西南大学新进教职工合同签订常见问题.pdf",
            "snippet": (
                "1 附件 8： 西南大学新进人员入职报到 常见问题解答 "
                "一、新进人员签订合同，哪些情况下签订有约定试用期的条款？ "
                "答：签订合同时，新进人员有以下情形的，需约定试用期。 "
                "二、聘用合同及岗位任务书中涉及的时间如何填写？ "
                "答：合同签订时间、合同开始时间以及岗位任务书落款时间应一致。"
            ),
            "score": 0.99,
        },
        {
            "doc_id": "doc-1",
            "document_title": "西南大学新进教职工合同签订常见问题.pdf",
            "page_number": 2,
            "section_title": "2 请各二级单位工作人员持旧材料至人力资源部重新领取",
            "snippet": (
                "四、合同正本和岗位任务书需要单位党政主要负责人签字盖章吗？ "
                "答：聘用合同正本中二级单位党组织、行政负责人均需签字。 "
                "五、人事档案未到校可以办理报到手续吗？ "
                "答：国内应届毕业生档案未到校可先办理报到手续。"
            ),
            "score": 0.95,
        },
    ]

    answer = agent._build_structured_summary(agent._select_summary_docs(agent._prioritize_summary_docs(docs)))

    assert "主要说明合同签订条件、合同与岗位任务书时间填写。" in answer
    assert "主要说明合同与岗位任务书签字盖章要求、档案到校与报到手续要求。" in answer
    assert "答：签订合同时" not in answer
