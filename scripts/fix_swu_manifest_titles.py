from __future__ import annotations

import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1] / "datasets" / "swu_public_docs"

SOURCE_TITLES = {
    "01_swu_procurement_management_measures_2018.pdf": "西南大学采购管理办法",
    "02_swu_capital_construction_management_measures.pdf": "西南大学基本建设管理办法",
    "03_swu_horizontal_research_project_management.pdf": "西南大学横向科研项目管理办法",
    "04_swu_2021_department_budget.pdf": "西南大学2021年部门预算",
    "05_swu_internal_control_audit_measures.html": "西南大学内部控制审计实施办法",
    "06_swu_finance_information_disclosure_rules.html": "西南大学财务信息公开实施细则",
    "07_swu_information_contract_workflow.html": "西南大学信息化项目合同审核流程",
    "08_swu_software_procurement_workflow.html": "西南大学软件采购流程",
    "09_swu_internal_audit_quality_control.html": "西南大学内部审计质量控制办法",
    "10_swu_internal_control_audit.html": "西南大学内部控制审计办法",
    "11_swu_internal_audit_rectification.html": "西南大学审计整改工作办法",
    "12_swu_equipment_contract_review.html": "西南大学设备类合同审核流程",
    "13_swu_new_staff_contract_faq.pdf": "西南大学新进教职工合同签订常见问题",
    "14_swu_new_staff_reporting_guide.pdf": "西南大学新进教职工报到指南",
    "15_swu_budget_performance_management_measures.pdf": "西南大学预算绩效管理办法",
    "16_swu_receivables_and_prepayments_management.pdf": "西南大学暂付款和应收及预付款项管理办法",
    "17_swu_balance_carryover_funds_management.pdf": "西南大学结转结余资金管理办法",
}

FAILED_TITLES = {
    "18_swu_domestic_travel_expense_management.pdf": "西南大学国内差旅费管理办法",
    "19_swu_economic_responsibility_system_measures.pdf": "西南大学经济责任制度实施办法",
    "20_swu_2023_department_budget.pdf": "西南大学2023年部门预算",
    "21_swu_2023_final_accounts.pdf": "西南大学2023年部门决算",
}


def rewrite(path: Path, title_map: dict[str, str]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data:
        title = title_map.get(item.get("filename"))
        if title:
            item["title"] = title
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    rewrite(BASE / "sources.json", SOURCE_TITLES)
    rewrite(BASE / "failed_sources.json", FAILED_TITLES)
