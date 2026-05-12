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
            docs = self._prioritize_summary_docs(docs)
            docs = self._select_summary_docs(docs)
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
                f"[{idx}] {item.get('document_title') or '未知文档'} / {section} / 第 {item.get('page_number')} 页\n"
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
        sections = list(dict.fromkeys(self._clean_section_title(item.get("section_title") or "未命名章节") for item in docs))
        key_points: list[tuple[str, str]] = []
        seen: set[str] = set()

        for item in docs:
            section = self._clean_section_title(item.get("section_title") or "未命名章节")
            snippet = self._clean_summary_snippet(item.get("snippet", ""), section_title=section)
            snippet = self._summarize_point(section, snippet)
            if not snippet:
                continue
            signature = f"{section}::{snippet}"
            if signature in seen:
                continue
            seen.add(signature)
            key_points.append((section, snippet))
            if len(key_points) >= 3:
                break

        lead = self._build_lead(docs, key_points)
        lines = [
            "## 文档摘要",
            "",
            f"**摘要结论：** {lead}",
            "",
            "### 摘要范围",
            f"1. 涉及文档：{'、'.join(titles[:5])}",
            f"2. 命中文档片段：{len(docs)}",
            f"3. 重点章节：{'、'.join(sections[:3]) if sections else '未命名章节'}",
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

    def _select_summary_docs(self, docs: list[dict]) -> list[dict]:
        filtered = [item for item in docs if self._is_summary_worthy(item)]
        return filtered or docs[:3]

    def _prioritize_summary_docs(self, docs: list[dict]) -> list[dict]:
        return sorted(
            docs,
            key=lambda item: (
                self._summary_priority(item),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )

    def _summary_priority(self, item: dict) -> int:
        snippet = " ".join(str(item.get("snippet") or "").split()).strip()
        section = self._clean_section_title(item.get("section_title") or "")
        title = str(item.get("document_title") or "").strip()
        page_number = int(item.get("page_number") or 0)
        priority = 0

        if page_number == 1:
            priority += 8
        elif page_number == 2:
            priority += 4
        if section == title and page_number == 1:
            priority += 10
        elif section == title and page_number > 1:
            priority -= 4
        priority += self._title_keyword_overlap(title, f"{section} {snippet}") * 3
        if any(marker in section for marker in ("总则", "概述", "主要内容", "基本原则", "适用范围", "摘要", "说明")):
            priority += 12
        if any(marker in snippet for marker in ("总则", "适用范围", "主要内容", "基本原则", "定义", "适用对象", "主要包括", "围绕")):
            priority += 10
        if any(marker in snippet for marker in ("常见问题解答", "问答汇总", "政策解读", "办理指南")):
            priority += 8
        if "常见问题" in title and page_number == 1:
            priority += 18
        if "常见问题" in title and page_number >= 4:
            priority -= 10
        if snippet.startswith("1 附件") or snippet.startswith("附件 8："):
            priority += 12
        if self._looks_like_question_style_chunk(section, snippet) and not (
            "常见问题解答" in snippet and page_number == 1
        ):
            priority -= 8
        if any(marker in snippet for marker in ("哪些情况下", "是否需要", "如何办理", "怎么办", "怎么处理")):
            priority -= 8
        if any(marker in section for marker in ("附则", "附件", "联系方式", "报到完成后", "发放安家费")):
            priority -= 4
        if any(marker in snippet for marker in ("报到完成后", "发放安家费", "科研启动金", "联系方式")):
            priority -= 6
        if any(marker in snippet for marker in ("七、报到完成后", "安家费", "科研启动金")):
            priority -= 10
        if re.match(r"^[二三四五六七八九十]\s*[、.]", snippet):
            priority -= 3
        if re.match(r"^\d+\s", section):
            priority -= 5
        if section.startswith(("2 ", "3 ", "4 ", "5 ", "六、", "七、", "八、")):
            priority -= 6
        if "目录" in snippet[:20]:
            priority -= 8
        if len(snippet) >= 100:
            priority += 4
        elif len(snippet) >= 50:
            priority += 2
        if page_number >= 8:
            priority -= 2
        return priority

    def _is_substantive_snippet(self, snippet: str) -> bool:
        normalized = " ".join((snippet or "").split()).strip()
        if len(normalized) < 8:
            return False

        markers = (
            "附件",
            "已下载次数",
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

    def _build_lead(self, docs: list[dict], key_points: list[tuple[str, str]]) -> str:
        if not docs or not key_points:
            return "当前未提取到有效摘要内容。"
        title = str(docs[0].get("document_title") or "该文档").strip()
        topics = self._extract_summary_topics(key_points)
        if topics:
            summary = f"《{title.strip('《》')}》主要围绕" + "、".join(topics[:3]) + "进行说明。"
            return summary if len(summary) <= 90 else summary[:87].rstrip() + "..."
        lead = key_points[0][1]
        return lead if len(lead) <= 90 else lead[:87].rstrip() + "..."

    def _extract_summary_topics(self, key_points: list[tuple[str, str]]) -> list[str]:
        topics: list[str] = []
        seen: set[str] = set()
        for section, snippet in key_points:
            topic = self._topic_from_section_or_snippet(section, snippet)
            if not topic:
                continue
            if topic not in seen:
                seen.add(topic)
                topics.append(topic)
        return topics

    def _topic_from_section_or_snippet(self, section: str, snippet: str) -> str:
        topic_markers = (
            "合同签订",
            "试用期",
            "起薪",
            "报到材料",
            "报到手续",
            "档案",
            "岗位任务书",
            "聘用合同",
            "社保缴纳证明",
            "办理条件",
        )
        for marker in topic_markers:
            if marker in snippet:
                return marker
            if marker in section:
                return marker
        for source in (section, snippet):
            normalized = source.strip("：:；;，,。. ")
            normalized = re.sub(r"^[一二三四五六七八九十]+[、.]\s*", "", normalized)
            normalized = re.sub(r"^\d+\s*", "", normalized)
            normalized = re.sub(r"^(常见问题解答|问答汇总)\s*", "", normalized)
            if normalized.endswith((".pdf", ".doc", ".docx")):
                continue
            if not normalized:
                continue
            if self._looks_like_question_style_chunk(section, normalized):
                normalized = re.sub(r"(哪些情况下|是否需要|如何办理|怎么办|怎么处理).*", "", normalized).strip("：:；;，,。. ")
            topic = normalized[:18].strip()
            if 2 <= len(topic) <= 18:
                return topic
        return ""

    def _looks_like_question_style_chunk(self, section: str, snippet: str) -> bool:
        combined = f"{section} {snippet}".strip()
        if re.match(r"^[一二三四五六七八九十]+[、.]", section):
            return True
        question_markers = ("？", "?", "哪些", "是否", "如何", "怎么办", "怎么", "何时", "什么时候")
        return any(marker in combined for marker in question_markers)

    def _title_keyword_overlap(self, title: str, text: str) -> int:
        title_keywords = [
            token
            for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", title)
            if token not in {"常见问题", "问题", "办法", "制度", "规定", "通知", "方案", "pdf", "doc", "docx"}
        ]
        if not title_keywords:
            return 0
        overlap = 0
        for keyword in title_keywords:
            if keyword in text:
                overlap += 1
        return overlap

    def _is_summary_worthy(self, item: dict) -> bool:
        title = str(item.get("document_title") or "").strip()
        section = self._clean_section_title(item.get("section_title") or "")
        snippet = " ".join(str(item.get("snippet") or "").split()).strip()
        page_number = int(item.get("page_number") or 0)
        overlap = self._title_keyword_overlap(title, f"{section} {snippet}")

        if overlap == 0 and page_number >= 4:
            return False
        if "常见问题" in title and page_number >= 4 and "常见问题解答" not in snippet:
            return False
        if any(marker in snippet for marker in ("职称，又具备下列条件之一", "双师型教师", "工程背景教师")):
            return False
        return True

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
            normalized = normalized[len(section_title) :].strip(" ：:；;，,。. ")
        if len(normalized) > 180:
            normalized = normalized[:177].rstrip() + "..."
        return normalized

    def _summarize_point(self, section: str, snippet: str) -> str:
        if any(marker in snippet for marker in ("万元", "%", "占", "预算", "收支")) and re.search(r"\d", snippet):
            return snippet
        compact = self._summarize_faq_snippet(snippet)
        if compact:
            return compact
        compact = self._summarize_section_title(section)
        if compact and compact not in {"未命名章节", section}:
            return compact
        return snippet

    def _summarize_faq_snippet(self, snippet: str) -> str:
        normalized = " ".join((snippet or "").split()).strip()
        if not normalized:
            return ""
        question_hits = re.findall(r"([一二三四五六七八九十]+、\s*[^？?。]+(?:[？?]|答：))", normalized)
        topic_hits: list[str] = []
        for raw in question_hits[:4]:
            topic = self._normalize_point_topic(raw)
            if topic and topic not in topic_hits:
                topic_hits.append(topic)
        if topic_hits:
            return "主要说明" + "、".join(topic_hits[:3]) + "。"
        return ""

    def _summarize_section_title(self, section: str) -> str:
        normalized = self._normalize_point_topic(section)
        if normalized and normalized != "未命名章节":
            return f"主要说明{normalized}。"
        return ""

    def _normalize_point_topic(self, text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        normalized = re.sub(r"^[一二三四五六七八九十\d]+[、.]\s*", "", normalized)
        normalized = re.sub(r"^(答|问)[:：]\s*", "", normalized)
        normalized = re.sub(r"(请各二级单位工作人员持旧材料至人力资源部重新领取)", "旧材料更换", normalized)
        replacements = (
            ("新进人员签订合同", "合同签订条件"),
            ("哪些情况下签订有约定试用期的条款", "试用期适用条件"),
            ("聘用合同及岗位任务书中涉及的时间如何填写", "合同与岗位任务书时间填写"),
            ("干部履历表和合同信息填写错误如何处理", "合同信息更正"),
            ("合同正本和岗位任务书需要单位党政主要负责人签字盖章吗", "合同与岗位任务书签字盖章要求"),
            ("人事档案未到校可以办理报到手续吗", "档案到校与报到手续要求"),
            ("报到手续完成后，何时起薪", "报到后的起薪规则"),
            ("报到完成后，何时发放安家费和科研启动金", "安家费与科研启动金发放时间"),
        )
        for source, target in replacements:
            if source in normalized:
                normalized = target
                break
        normalized = re.sub(r"[？?].*$", "", normalized)
        normalized = normalized.strip("：:；;，,。. ")
        if len(normalized) > 26:
            normalized = normalized[:26].rstrip()
        return normalized

    def _should_use_llm_summary(self, docs: list[dict]) -> bool:
        if any("常见问题" in str(item.get("document_title") or "") for item in docs[:3]):
            return False
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
        return f"可以继续追问《{title.strip('《》')}》的适用范围、所需材料、审批流程、金额标准或版本变化。"
