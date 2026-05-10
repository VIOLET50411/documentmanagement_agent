"""Summary agent fallback implementation."""

from __future__ import annotations

from app.agent.agents.compliance_agent import ComplianceAgent
from app.services.llm_service import LLMService


class SummaryAgent:
    """Specialist agent for document summarization and extraction."""

    async def run(self, state: dict) -> dict:
        state = await ComplianceAgent().run(state)
        docs = state.get("retrieved_docs") or []
        if not docs:
            state["answer"] = "当前没有可供摘要的文档内容。"
        elif not any(self._is_substantive_snippet(item.get("snippet", "")) for item in docs):
            state["answer"] = (
                "## 未提取到足够正文\n\n"
                "当前仅命中标题页、附件页或站点页脚信息，无法形成可靠摘要。\n\n"
                "建议重新上传正文更完整的文档版本，或指定更具体的章节后再试。"
            )
            state["citations"] = self._build_citations(docs[:1])
        else:
            tenant_key = str(getattr(state.get("current_user"), "tenant_id", "default") or "default")
            llm_answer = await self._try_llm_summary(docs, tenant_key=tenant_key)
            if llm_answer:
                state["answer"] = llm_answer
            else:
                state["answer"] = self._build_structured_summary(docs)
            state["citations"] = self._build_citations(docs)
        state["agent_used"] = "summary"
        return state

    async def _try_llm_summary(self, docs: list[dict], tenant_key: str) -> str | None:
        context = []
        for idx, item in enumerate(docs[:8], start=1):
            context.append(
                f"[{idx}] {item.get('document_title') or '未知文档'} / {item.get('section_title') or '未命名章节'} / 页{item.get('page_number')}\n"
                f"{(item.get('snippet') or '').strip()[:450]}"
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
            system_prompt="你是企业知识管理助手。请输出清晰、可执行的中文摘要。",
            user_prompt=prompt,
            temperature=0.15,
            max_tokens=600,
            tenant_key=tenant_key,
        )

    def _normalize(self, text: str) -> str:
        snippet = " ".join((text or "").split())
        if len(snippet) > 180:
            snippet = snippet[:177].rstrip() + "..."
        return snippet

    def _build_structured_summary(self, docs: list[dict]) -> str:
        titles = list(dict.fromkeys(item.get("document_title", "未知文档") for item in docs))
        sections = list(dict.fromkeys((item.get("section_title") or "未命名章节") for item in docs))
        key_points = []
        seen = set()
        for item in docs:
            snippet = self._normalize(item.get("snippet", ""))
            if not snippet or snippet in seen:
                continue
            seen.add(snippet)
            key_points.append(snippet)
            if len(key_points) >= 3:
                break

        lead = key_points[0] if key_points else "当前未提取到有效摘要内容。"
        lines = [
            "## 文档摘要",
            "",
            f"**摘要结论：** {lead}",
            "",
            "### 摘要范围",
            f"1. 涉及文档：{', '.join(titles[:5])}",
            f"2. 命中片段数：{len(docs)}",
            f"3. 重点章节：{', '.join(sections[:3]) if sections else '未命名章节'}",
            "",
            "### 关键要点",
        ]
        if key_points:
            for index, point in enumerate(key_points, start=1):
                lines.append(f"{index}. {point}")
        else:
            lines.append("1. 当前未提取到足够的文档片段，请缩小范围或补充文档。")

        lines.extend(
            [
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
        if len(normalized) < 20:
            return False
        markers = ("附件【", "已下载次", "访问者", "版权所有", "地址：", "邮编：", "传真：")
        marker_hits = sum(1 for marker in markers if marker in normalized)
        return marker_hits < 2
