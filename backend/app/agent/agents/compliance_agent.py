"""Compliance agent fallback implementation."""

from __future__ import annotations

import re
from collections import OrderedDict

from app.services.llm_service import LLMService


class ComplianceAgent:
    """Specialist agent for regulatory and policy document Q&A."""

    async def run(self, state: dict) -> dict:
        from app.retrieval.hybrid_searcher import HybridSearcher

        searcher = HybridSearcher()
        query = (state.get("rewritten_query") or state["query"]).strip()
        results = await searcher.search(query=query, user=state["current_user"], top_k=5, search_type=state.get("search_type", "hybrid"), db=state["db"])
        state["retrieved_docs"] = results
        state["citations"] = [
            {
                "doc_id": item["doc_id"],
                "doc_title": item.get("document_title", "未知文档"),
                "page_number": item.get("page_number"),
                "section_title": item.get("section_title"),
                "snippet": item.get("snippet", ""),
                "relevance_score": item.get("score", 0.0),
            }
            for item in results
        ]

        if not results:
            state["answer"] = "当前权限范围内未检索到可直接支持该问题的文档内容。请补充文档名称、年份或部门范围后重试。"
        else:
            llm_answer = await self._try_llm_answer(state, query, results)
            if llm_answer:
                state["answer"] = llm_answer
            elif state.get("intent") == "compare":
                state["answer"] = self._build_compare_answer(query, results)
            else:
                state["answer"] = self._build_qa_answer(query, results)

        state["agent_used"] = "compliance"
        return state

    async def _try_llm_answer(self, state: dict, query: str, results: list[dict]) -> str | None:
        context_lines = []
        for idx, item in enumerate(results[:5], start=1):
            title = item.get('document_title') or '未知文档'
            section = item.get('section_title') or '未命名章节'
            snippet = (item.get('snippet') or '').strip()[:300]
            context_lines.append(
                f"[证据{idx}] 《{title}》{section}\n{snippet}"
            )
        prompt = (
            f"## 用户问题\n{query}\n\n"
            f"## 文档证据\n" + "\n\n".join(context_lines) + "\n\n"
            f"## 回答要求\n"
            "请用结构化的中文回答：\n"
            "1. 先给出简明结论\n"
            "2. 再用编号列表展开2-4条关键要点\n"
            "3. 标注引用来源 [来源: 文档标题]\n"
            "4. 不要编造证据外信息"
        )
        llm = LLMService()
        answer = await llm.generate(
            system_prompt=(
                "你是企业文档问答助手 DocMind。\n"
                "严格依据提供的文档证据回答用户问题。\n"
                "使用清晰、专业的简体中文，善用 Markdown 格式。\n"
                "如果证据不足，明确说明。绝不编造。"
            ),
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=800,
            tenant_key=str(getattr(state.get("current_user"), "tenant_id", "default") or "default"),
        )
        # Validate output quality — reject garbled text
        if answer and len(answer.strip()) > 10:
            chinese_chars = sum(1 for c in answer if '\u4e00' <= c <= '\u9fff')
            non_space = len(answer.replace(" ", "").replace("\n", ""))
            if non_space > 0 and chinese_chars / non_space > 0.08:
                return answer.strip()
        return None

    def _build_qa_answer(self, query: str, results: list[dict]) -> str:
        top = results[0]
        conclusion = self._extract_best_evidence(query, top.get("snippet", ""))
        lines = [
            f"## 关于「{query}」\n",
            f"**结论**：{conclusion}\n",
            "### 相关依据\n",
        ]
        for index, item in enumerate(results[:3], start=1):
            evidence = self._extract_best_evidence(query, item.get("snippet", ""))
            lines.append(f"{index}. **{self._format_source(item)}**\n   {evidence}\n")
        lines.append("---")
        lines.append("> 以上内容基于知识库检索结果整理，请以原始制度正文为准。如需更详细解读，请上传相关制度文件。")
        return "\n".join(lines)

    def _build_compare_answer(self, query: str, results: list[dict]) -> str:
        grouped = self._group_by_document(results)
        if len(grouped) < 2:
            return self._build_qa_answer(query, results)
        doc_items = list(grouped.items())[:2]
        left_title, left_results = doc_items[0]
        right_title, right_results = doc_items[1]
        left_text = self._extract_best_evidence(query, left_results[0].get("snippet", ""))
        right_text = self._extract_best_evidence(query, right_results[0].get("snippet", ""))
        left_diff = self._extract_keywords(left_text)
        right_diff = self._extract_keywords(right_text)
        diff = "文档A强调：{}；文档B强调：{}".format("、".join(left_diff[:3]) or "无", "、".join(right_diff[:3]) or "无")
        return "\n".join([
            f"## 对比分析：《{left_title}》vs《{right_title}》\n",
            "| 主题 | 文档A | 文档B | 差异说明 |",
            "| --- | --- | --- | --- |",
            "--- | --- | --- | ---",
            f"| 核心要求 | {left_text} | {right_text} | {diff} |",
        ])

    def _group_by_document(self, results: list[dict]) -> OrderedDict[str, list[dict]]:
        grouped: OrderedDict[str, list[dict]] = OrderedDict()
        for item in results:
            title = item.get("document_title") or "未知文档"
            grouped.setdefault(title, []).append(item)
        return grouped

    def _extract_best_evidence(self, query: str, text: str) -> str:
        table_hit = self._extract_from_markdown_table(query, text)
        if table_hit:
            return table_hit
        normalized = self._normalize_text(text)
        if not normalized:
            return "未提取到有效证据。"
        sentences = [segment.strip() for segment in re.split(r"[。；\n]", normalized) if segment.strip()]
        if not sentences:
            return normalized
        keywords = self._extract_keywords(query)
        scored = []
        for sentence in sentences:
            score = sum(1 for keyword in keywords if keyword and keyword in sentence)
            scored.append((score, sentence))
        scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        return scored[0][1]

    def _extract_from_markdown_table(self, query: str, text: str) -> str:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip().startswith("|")]
        aliases = self._build_aliases(query)
        best = ""
        best_score = -1
        for line in lines:
            columns = [col.strip() for col in line.strip("|").split("|")]
            if len(columns) < 2:
                continue
            joined = " ".join(columns).lower()
            if joined.startswith("policy content") or joined.startswith("---"):
                continue
            score = sum(2 for alias in aliases if alias in joined)
            candidate = columns[-1]
            if score > best_score and candidate and candidate != "---":
                best = candidate
                best_score = score
        return self._normalize_text(best)

    def _build_aliases(self, query: str) -> list[str]:
        aliases = []
        if any(token in query for token in ("年假", "请假", "休假")):
            aliases.extend(["leave", "vacation", "holiday", "年假", "请假", "休假"])
        if any(token in query for token in ("报销", "差旅", "出差")):
            aliases.extend(["travel", "expense", "reimburse", "报销", "差旅", "出差"])
        if not aliases:
            aliases.extend(self._extract_keywords(query))
        deduped = []
        seen = set()
        for alias in aliases:
            lower = alias.lower()
            if lower not in seen:
                seen.add(lower)
                deduped.append(lower)
        return deduped

    def _extract_keywords(self, query: str) -> list[str]:
        lowered = query.lower()
        terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", lowered)
        keywords = []
        for term in terms:
            if len(term) >= 2:
                keywords.append(term)
                if re.search(r"[\u4e00-\u9fff]", term) and len(term) > 2:
                    keywords.extend(term[i : i + 2] for i in range(len(term) - 1))
        ordered = []
        seen = set()
        for keyword in keywords:
            if keyword not in seen:
                seen.add(keyword)
                ordered.append(keyword)
        return ordered

    def _format_source(self, item: dict) -> str:
        title = item.get("document_title") or "未知文档"
        section = item.get("section_title") or "未命名章节"
        page = item.get("page_number")
        if page is None:
            return f"《{title}》 {section}"
        return f"《{title}》 第 {page} 页 / {section}"

    def _normalize_text(self, text: str) -> str:
        snippet = " ".join((text or "").split())
        if len(snippet) > 160:
            snippet = snippet[:157].rstrip() + "..."
        return snippet
