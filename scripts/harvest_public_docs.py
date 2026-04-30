from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"


@dataclass(frozen=True)
class Source:
    filename: str
    title: str
    category: str
    source_type: str
    url: str
    expected_kind: str
    replaces: tuple[str, ...] = ()


SWU_ROUND_2: tuple[Source, ...] = (
    Source(
        filename="18_swu_domestic_official_reception_rules.pdf",
        title="西南大学国内公务接待管理实施细则（修订）",
        category="approval",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/D/AA/12/A1901D685B9463801F7CC6539D4_00A9CE48_4677B.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="19_swu_state_owned_assets_management_2021.pdf",
        title="西南大学国有资产管理办法",
        category="procurement",
        source_type="swu_direct_pdf",
        url="https://gzhqc.swu.edu.cn/__local/8/29/59/12AF80048383E818C9F6889CFEF_DAE422D7_9E4DA.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="20_swu_basic_construction_finance_management_revised.pdf",
        title="西南大学基本建设财务管理办法（修订）",
        category="budget",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/5/B4/59/F553B4AE8ABBF43EA3BD785F8EB_7FAEACE0_6AAEC.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="21_swu_fixed_assets_management.pdf",
        title="西南大学固定资产管理办法",
        category="procurement",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/9/6A/CB/C5776A70734F970DC29C6185364_B8575282_78A36.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="22_swu_intangible_assets_management.pdf",
        title="西南大学无形资产管理办法",
        category="compliance",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/F/6E/5E/01AAA150914A64B4EAF1E309717_193B72C9_5A025.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="23_swu_state_property_registration_rules.pdf",
        title="西南大学国有资产产权登记管理办法",
        category="compliance",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/2/28/C8/BAE1153AA3EE3A2A1772A24AFB5_AEA41675_31C69.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="24_swu_financial_reimbursement_rules.pdf",
        title="西南大学财务报销规范",
        category="approval",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/4/A3/F5/7DC3FD1B4EB5C28D17893C3A36E_879175C8_43380.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="25_swu_special_funds_management_rules.pdf",
        title="西南大学专项资金管理办法",
        category="budget",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/F/97/EF/32EEB167E5557EF67CE3B9FB764_7C11A16D_4A255.pdf?e=.pdf",
        expected_kind="pdf",
    ),
    Source(
        filename="26_swu_state_owned_assets_management_2019.pdf",
        title="西南大学国有资产管理办法（修订）",
        category="procurement",
        source_type="swu_direct_pdf",
        url="https://xxgk.swu.edu.cn/__local/F/D2/07/6936D1115185CD00CDCFC8D2416_6DF0E4EE_81E8B.pdf?e=.pdf",
        expected_kind="pdf",
    ),
)


PROFILES = {
    "swu_round_2": ("swu_public_docs", SWU_ROUND_2),
}

SWU_PAGE_ROUND_3: tuple[Source, ...] = (
    Source(
        filename="18_swu_domestic_travel_expense_management.html",
        title="西南大学国内差旅费管理办法",
        category="approval",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1092/3440.htm",
        expected_kind="html",
        replaces=("18_swu_domestic_travel_expense_management.pdf",),
    ),
    Source(
        filename="19_swu_economic_responsibility_system_measures.html",
        title="西南大学经济责任制实施办法",
        category="compliance",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1113/3253.htm",
        expected_kind="html",
        replaces=("19_swu_economic_responsibility_system_measures.pdf",),
    ),
    Source(
        filename="20_swu_2023_department_budget.html",
        title="西南大学2023年度部门预算",
        category="budget",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1117/3638.htm",
        expected_kind="html",
        replaces=("20_swu_2023_department_budget.pdf",),
    ),
    Source(
        filename="21_swu_2023_final_accounts.html",
        title="西南大学2023年度决算公开",
        category="budget",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1118/4297.htm",
        expected_kind="html",
        replaces=("21_swu_2023_final_accounts.pdf",),
    ),
    Source(
        filename="27_swu_2024_department_budget.html",
        title="西南大学2024年度部门预算",
        category="budget",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1117/4187.htm",
        expected_kind="html",
    ),
    Source(
        filename="28_swu_2024_final_accounts.html",
        title="西南大学2024年度决算公开",
        category="budget",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1118/4587.htm",
        expected_kind="html",
    ),
    Source(
        filename="29_swu_vertical_research_fund_management.html",
        title="西南大学纵向科研项目资金管理办法",
        category="contract",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1113/3520.htm",
        expected_kind="html",
    ),
    Source(
        filename="30_swu_research_package_fund_management.html",
        title="西南大学“包干制”科研项目资金管理办法",
        category="contract",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1113/3518.htm",
        expected_kind="html",
    ),
    Source(
        filename="31_swu_central_research_fund_management.html",
        title="西南大学中央高校基本科研业务费专项资金管理办法",
        category="contract",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1092/3230.htm",
        expected_kind="html",
    ),
    Source(
        filename="32_swu_graduate_research_innovation_project_management.html",
        title="西南大学研究生科研创新项目管理办法（试行）",
        category="contract",
        source_type="swu_page_html",
        url="https://xxgk.swu.edu.cn/info/1092/3645.htm",
        expected_kind="html",
    ),
)

PROFILES["swu_page_round_3"] = ("swu_public_docs", SWU_PAGE_ROUND_3)


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: list[dict]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_pdf(response: requests.Response) -> None:
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        raise ValueError("returned_html_instead_of_document")
    if not response.content.startswith(b"%PDF"):
        raise ValueError("response_is_not_pdf")


def ensure_html(response: requests.Response) -> str:
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type:
        raise ValueError("response_is_not_html")
    for encoding in ("utf-8", response.apparent_encoding, response.encoding, "gb18030"):
        if not encoding:
            continue
        try:
            text = response.content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = response.content.decode("utf-8", errors="ignore")
    return text.lstrip("\ufeff").lstrip("ï»¿")


def download_source(raw_dir: Path, source: Source) -> dict:
    response = requests.get(
        source.url,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()

    saved_path = raw_dir / source.filename
    if source.expected_kind == "pdf":
        ensure_pdf(response)
        saved_path.write_bytes(response.content)
        size = len(response.content)
    elif source.expected_kind == "html":
        text = ensure_html(response)
        saved_path.write_text(text, encoding="utf-8")
        size = len(text.encode("utf-8"))
    else:
        raise ValueError(f"unsupported_expected_kind:{source.expected_kind}")

    return {
        **asdict(source),
        "saved_path": str(saved_path),
        "bytes": size,
        "content_type": response.headers.get("content-type", ""),
    }


def run_profile(dataset_name: str, sources: Iterable[Source]) -> dict:
    dataset_dir = DATASETS_DIR / dataset_name
    raw_dir = dataset_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    sources_path = dataset_dir / "sources.json"
    failed_path = dataset_dir / "failed_sources.json"
    current_sources = load_json(sources_path)
    current_failed = load_json(failed_path)
    existing_filenames = {item.get("filename") for item in current_sources}
    failed_filenames = {item.get("filename") for item in current_failed}

    added = 0
    retried = 0
    for source in sources:
        if source.filename in existing_filenames:
            continue
        current_failed = [item for item in current_failed if item.get("filename") != source.filename]
        for old_name in source.replaces:
            current_failed = [item for item in current_failed if item.get("filename") != old_name]
        if source.filename in failed_filenames:
            retried += 1
        try:
            entry = download_source(raw_dir, source)
            current_sources.append(entry)
            added += 1
        except Exception as exc:  # noqa: BLE001
            current_failed.append(
                {
                    **asdict(source),
                    "error": str(exc),
                }
            )

    save_json(sources_path, current_sources)
    save_json(failed_path, current_failed)
    return {
        "dataset": dataset_name,
        "added": added,
        "retried": retried,
        "total_valid": len(current_sources),
        "total_failed": len(current_failed),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=sorted(PROFILES))
    args = parser.parse_args()
    dataset_name, sources = PROFILES[args.profile]
    result = run_profile(dataset_name, sources)
    print(json.dumps(result, ensure_ascii=False))
