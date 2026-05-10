"""Summary agent with grounded, evidence-first fallback behavior."""

from __future__ import annotations

import re

from app.agent.agents.compliance_agent import ComplianceAgent
from app.services.llm_service import LLMService


class SummaryAgent:
    """Specialist agent for document summarization and extraction."""

    async def run(self, state: dict) -> dict:
        state = await ComplianceAgent().run(state)
        docs = state.get("retrieved_docs") or []

        if not docs:
            state["answer"] = "当前没有可供摘要的文档内容。"
            state["citations"] = []
        elif not any(self._is_substantive_snippet(item.get("snippet", "")) for item in docs):
            state["answer"] = (
                "## 未提取到足够正文\n\n"
                "当前仅命中标题页、附件页或站点页脚信息，无法形成可靠摘要。\n\n"
                "建议重新上传正文更完整的文档版本，或指定更具体的章节后再试。"
            )
            state["citations"] = self._build_citations(docs[:1])
        else:
            state["answer"] = self._build_structured_summary(docs)
            if self._should_use_llm_summary(docs):
                tenant_key = str(getattr(state.get("current_user"), "tenant_id", "default") or "default")
                llm_answer = await self._try_llm_summary(docs, tenant_key=tenant_key)
                if llm_answer and self._is_grounded_summary(llm_answer):
                    state["answer"] = llm_answer
            state["citations"] = self._build_citations(docs)

        state["agent_used"] = "summary"
        return state

    async def _try_llm_summary(self, docs: list[dict], tenant_key: str) -> str | None:
        context = []
        for idx, item in enumerate(docs[:8], start=1):
            section = self._clean_section_title(item.get("section_title") or "未命名章节")
            snippet = self._clean_summary_snippet(item.get("snippet", ""), section_title=section)
            context.append(
                f"[{idx}] {item.get('document_title') or '未知文档'} / {section} / 页 {item.get('page_number')}\n"
                f"{snippet[:450]}"
            )

        prompt = (
            "请根据以下文档片段输出结构化摘要。\n\n"
            + "\n\n".join(context)
            + "\n\n输出格式：\n"
            "- 一句话总结\n"
            "- 三条关键要点\n"
            "- 两条执行建议"
        )
        return await LLMService().generate(
            system_prompt="你是企业知识管理助手。请输出清晰、可执行、严格基于证据的中文摘要。",
            user_prompt=prompt,
            temperature=0.15,
            max_tokens=600,
            tenant_key=tenant_key,
        )

    def _build_structured_summary(self, docs: list[dict]) -> str:
        titles = list(dict.fromkeys(item.get("document_title", "未知文档") for item in docs))
        sections = list(
            dict.fromkeys(self._clean_section_title(item.get("section_title") or "未命名章节") for item in docs)
        )
        key_points: list[tuple[str, str]] = []
        seen: set[str] = set()

        for item in docs:
            section = self._clean_section_title(item.get("section_title") or "未命名章节")
            snippet = self._clean_summary_snippet(item.get("snippet", ""), section_title=section)
            if not snippet:
                continue
            signature = f"{section}::{snippet}"
            if signature in seen:
                continue
            seen.add(signature)
            key_points.append((section, snippet))
            if len(key_points) >= 3:
                break

        lead = self._build_lead(key_points)
        lines = [
            "## 文档摘要",
            "",
            f"**摘要结论：** {lead}",
            "",
            "### 摘要范围",
            f"1. 涉及文档：{', '.join(titles[:5])}",
            f"2. 命中文档片段：{len(docs)}",
            f"3. 重点章节：{', '.join(sections[:3]) if sections else '未命名章节'}",
            "",
            "### 关键要点",
        ]

        if key_points:
            for index, (section, point) in enumerate(key_points, start=1):
                lines.append(f"{index}. {section}：{point}")
        else:
            lines.append("1. 当前未提取到足够的文档片段，请缩小范围或补充文档。")

        lines.extend(
            [
                "",
                "### 待确认事项",
                f"1. {self._build_pending_item(docs, key_points)}",
                "",
                "### 建议追问",
                f"1. {self._build_follow_up_prompt(docs)}",
                "",
                "---",
                "> 以上摘要基于当前检索到的文档片段整理，请结合原始文档复核。",
            ]
        )
        return "\n".join(lines)

    def _build_citations(self, docs: list[dict]) -> list[dict]:
        return [
            {
                "doc_id": item.get("doc_id"),
                "doc_title": item.get("document_title", "未知文档"),
                "page_number": item.get("page_number"),
                "section_title": item.get("section_title"),
                "snippet": item.get("snippet", ""),
                "relevance_score": item.get("score", 0.0),
            }
            for item in docs[:3]
        ]

    def _is_substantive_snippet(self, snippet: str) -> bool:
        normalized = " ".join((snippet or "").split()).strip()
        if len(normalized) < 8:
            return False

        markers = (
            "附件",
            "已下载次",
            "访问者",
            "版权所有",
            "地址：",
            "邮编：",
            "传真：",
        )
        marker_hits = sum(1 for marker in markers if marker in normalized)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", normalized))
        digits = len(re.findall(r"\d", normalized))

        if marker_hits >= 2:
            return False
        if chinese_chars >= 6:
            return True
        return len(normalized) >= 20 or (chinese_chars >= 4 and digits >= 2)

    def _build_lead(self, key_points: list[tuple[str, str]]) -> str:
        if not key_points:
            return "当前未提取到有效摘要内容。"
        lead = key_points[0][1]
        return lead if len(lead) <= 90 else lead[:87].rstrip() + "..."

    def _clean_section_title(self, section: str) -> str:
        cleaned = " ".join((section or "").split()).strip()
        cleaned = re.sub(r"^20\s+swu\s+\d{4}.*budget.*$", "预算相关章节", cleaned, flags=re.IGNORECASE)
        return cleaned or "未命名章节"

    def _clean_summary_snippet(self, snippet: str, *, section_title: str) -> str:
        normalized = " ".join((snippet or "").split()).strip()
        if not normalized:
            return ""
        normalized = re.sub(r"^\d+\s*", "", normalized)
        if section_title and normalized.startswith(section_title):
            normalized = normalized[len(section_title) :].strip(" ：:;；，,。.、")
        if len(normalized) > 180:
            normalized = normalized[:177].rstrip() + "..."
        return normalized

    def _should_use_llm_summary(self, docs: list[dict]) -> bool:
        joined = "\n".join(str(item.get("snippet") or "") for item in docs[:3])
        heuristic_markers = ("万元", "情况说明", "项目绩效", "审批", "流程", "依据", "制度")
        return not any(marker in joined for marker in heuristic_markers)

    def _is_grounded_summary(self, answer: str) -> bool:
        text = " ".join((answer or "").split()).strip()
        if len(text) < 24:
            return False
        if "根据提供的文档证据" in text and "未在提供的证据中详细列出" in text:
            return False
        return True

    def _build_pending_item(self, docs: list[dict], key_points: list[tuple[str, str]]) -> str:
        if len(docs) < 2:
            return "当前摘要基于较少片段整理，若需完整结论，建议补充更完整正文或指定章节。"
        if not key_points:
            return "当前未形成稳定摘要要点，建议缩小问题范围或重新指定文档。"
        return "如需用于执行，请继续确认适用对象、时间范围和例外情形。"

    def _build_follow_up_prompt(self, docs: list[dict]) -> str:
        title = str((docs[0] if docs else {}).get("document_title") or "该文档").strip()
        return f"可以继续追问《{title}》的适用范围、审批流程、金额标准或版本变化。"
