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
        else:
            tenant_key = str(getattr(state.get("current_user"), "tenant_id", "default") or "default")
            llm_answer = await self._try_llm_summary(docs, tenant_key=tenant_key)
            if llm_answer:
                state["answer"] = llm_answer
            else:
                titles = list(dict.fromkeys(item.get("document_title", "未知文档") for item in docs))
                sections = list(dict.fromkeys((item.get("section_title") or "未命名章节") for item in docs[:5]))
                lead = self._normalize(docs[0].get("snippet", ""))
                lines = [
                    "文档摘要：",
                    f"- 涉及文档：{', '.join(titles[:5])}",
                    f"- 命中片段数：{len(docs)}",
                    f"- 重点章节：{', '.join(sections[:3])}",
                    f"- 核心摘要：{lead}",
                ]
                if len(docs) > 1:
                    lines.append(f"- 补充信息：{self._normalize(docs[1].get('snippet', ''))}")
                state["answer"] = "\n".join(lines)
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
