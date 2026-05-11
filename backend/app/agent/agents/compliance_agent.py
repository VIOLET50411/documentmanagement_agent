"""Compliance agent fallback implementation."""

from __future__ import annotations

import re
from collections import OrderedDict

from app.services.llm_service import LLMService

LEAVE_ALIAS_MARKERS = ("年假", "请假", "休假")
TRAVEL_ALIAS_MARKERS = ("报销", "差旅", "出差")
GARBLED_MARKERS = ("\u951f",)


class ComplianceAgent:
    """Specialist agent for regulatory and policy document Q&A."""

    async def run(self, state: dict) -> dict:
        from app.agent.nodes.evidence_pack import build_evidence_pack
        from app.agent.nodes.retriever import _normalize_retrieved_results, resolve_retrieval_plan
        from app.retrieval.hybrid_searcher import HybridSearcher

        searcher = HybridSearcher()
        query = (state.get("rewritten_query") or state["query"]).strip()
        plan = resolve_retrieval_plan(state)
        results = await searcher.search(
            query=query,
            user=state["current_user"],
            top_k=plan["top_k"],
            search_type=plan["search_type"],
            db=state["db"],
        )
        results = _normalize_retrieved_results(
            searcher,
            query=query,
            results=results,
            plan=plan,
            conversation_state=state.get("conversation_state"),
        )

        state["retrieved_docs"] = results
        state["retrieval_plan"] = plan
        state["citations"] = self._build_citations(results)
        evidence_pack = build_evidence_pack(results, query=query)
        state["evidence_pack"] = evidence_pack
        task_mode = str(state.get("task_mode") or "qa")

        if not results:
            state["answer"] = "当前权限范围内未检索到可直接支撑该问题的文档内容。请补充文档名称、年份或部门范围后重试。"
        else:
            llm_answer = await self._try_llm_answer(state, query, results, evidence_pack=evidence_pack, task_mode=task_mode)
            if llm_answer:
                state["answer"] = llm_answer
            elif state.get("intent") == "compare":
                state["answer"] = self._build_compare_answer(query, results)
            elif task_mode == "process":
                state["answer"] = self._build_process_answer(query, results)
            else:
                state["answer"] = self._build_qa_answer(query, results)

        state["agent_used"] = "compliance"
        return state

    def _build_citations(self, results: list[dict]) -> list[dict]:
        return [
            {
                "doc_id": item.get("doc_id"),
                "doc_title": item.get("document_title", "未知文档"),
                "page_number": item.get("page_number"),
                "section_title": item.get("section_title"),
                "snippet": item.get("snippet", ""),
                "relevance_score": item.get("score", 0.0),
            }
            for item in results
        ]

    async def _try_llm_answer(self, state: dict, query: str, results: list[dict], *, evidence_pack: dict, task_mode: str) -> str | None:
        context_lines = []
        salient_points = evidence_pack.get("salient_points") if isinstance(evidence_pack.get("salient_points"), list) else []
        source_items = salient_points[:5] if salient_points else results[:5]
        for idx, item in enumerate(source_items, start=1):
            title = item.get("document_title") or "未知文档"
            section = item.get("section_title") or "未命名章节"
            snippet = (item.get("snippet") or "").strip()[:300]
            category = item.get("category")
            context_lines.append(f"[证据{idx}] 《{title}》 {section}" + (f" / {category}" if category else "") + f"\n{snippet}")

        conversation_state = state.get("conversation_state") if isinstance(state.get("conversation_state"), dict) else {}

        prompt = (
            f"## 用户问题\n{query}\n\n"
            f"## 任务模式\n{task_mode}\n\n"
            f"## 对话上下文\n"
            f"主题：{conversation_state.get('subject') or '未识别'}\n"
            f"追问：{'是' if conversation_state.get('is_follow_up') else '否'}\n"
            f"版本：{conversation_state.get('version_scope') or '未指定'}\n\n"
            f"## 文档证据\n{chr(10).join(context_lines)}\n\n"
            "## 回答要求\n"
            "请用结构化简体中文回答：\n"
            "1. 先给出简明结论；\n"
            "2. 再用 2-4 条编号列表展开关键要点；\n"
            "3. 如果是流程题，要按步骤组织；如果是提取题，要列出字段、条件和边界；\n"
            "4. 在对应要点后标注引用来源，格式为 [来源: 文档标题]；\n"
            "5. 不要编造证据之外的信息。"
        )
        answer = await LLMService().generate(
            system_prompt=(
                "你是企业制度问答助手 DocMind。\n"
                "请严格依据提供的文档证据回答用户问题。\n"
                "使用清晰、专业的简体中文，必要时用 Markdown 组织结构。\n"
                "如果证据不足，要明确说明，不得虚构。"
            ),
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=800,
            tenant_key=str(getattr(state.get("current_user"), "tenant_id", "default") or "default"),
        )
        if self._is_valid_chinese_answer(answer):
            return answer.strip()
        return None

    def _build_qa_answer(self, query: str, results: list[dict]) -> str:
        top = self._select_primary_result(query, results)
        conclusion = self._extract_best_evidence(query, top.get("snippet", ""))
        if conclusion == "未提取到有效证据。":
            conclusion = "当前证据不足以直接回答该问题，建议补充文档名称、版本或章节范围后重试。"
        source = self._format_source(top)
        raw_snippet = str(top.get("snippet", "") or "")
        evidence_excerpt = conclusion if "|" in raw_snippet else self._normalize_text(raw_snippet)
        follow_up = self._build_follow_up_hint(query, results)
        lines = [
            f"## 关于“{query}”的回答",
            "",
            f"**结论：** {conclusion}",
            "",
            "### 相关依据",
            f"1. {source}",
            f"   - 证据摘录：{evidence_excerpt}",
            "",
            "### 待确认事项",
            f"1. {follow_up}",
            "---",
            "> 以上内容基于知识库检索结果整理，请以原始制度正文为准。",
        ]
        return "\n".join(lines).strip()

    def _build_process_answer(self, query: str, results: list[dict]) -> str:
        steps = []
        seen = set()
        for item in results[:4]:
            snippet = self._normalize_text(item.get("snippet", ""))
            if not snippet or snippet in seen:
                continue
            seen.add(snippet)
            steps.append((self._format_source(item), snippet))
        lines = [
            f"## 关于“{query}”的流程说明",
            "",
            f"**流程结论：** {steps[0][1] if steps else '当前已命中相关文档，但暂未提取到清晰流程证据。'}",
            "",
            "### 关键步骤 / 依据",
        ]
        if steps:
            for index, (source, snippet) in enumerate(steps, start=1):
                lines.append(f"{index}. {snippet}")
                lines.append(f"   - 来源：{source}")
        else:
            lines.append("1. 当前证据不足以还原稳定流程，请补充更具体的问题或章节。")
        lines.extend(
            [
                "",
                "### 建议追问",
                "1. 如需落地执行，可继续追问每一步的责任人、所需材料和例外情况。",
            ]
        )
        return "\n".join(lines).strip()

    def _build_compare_answer(self, query: str, results: list[dict]) -> str:
        grouped = self._group_by_document(results)
        if len(grouped) < 2:
            only_title = next(iter(grouped.keys()), "当前命中文档")
            return "\n".join(
                [
                    f"## 关于“{query}”的对比结果",
                    "",
                    f"**结论：** 当前仅检索到 1 份文档《{only_title}》，无法完成可靠对比。",
                    "",
                    "### 待补充信息",
                    "1. 请补充另一份制度的名称、年份或版本号。",
                    "2. 若需要做同制度新旧版本对比，请明确“上一版、2023版、2024版”等范围。",
                ]
            ).strip()

        doc_items = list(grouped.items())[:2]
        left_title, left_results = doc_items[0]
        right_title, right_results = doc_items[1]
        left_text = self._extract_best_evidence(query, left_results[0].get("snippet", ""))
        right_text = self._extract_best_evidence(query, right_results[0].get("snippet", ""))
        left_diff = self._extract_keywords(left_text)
        right_diff = self._extract_keywords(right_text)
        diff = "文档 A 强调：{}；文档 B 强调：{}".format(
            "、".join(left_diff[:3]) or "暂无明显差异点",
            "、".join(right_diff[:3]) or "暂无明显差异点",
        )
        return "\n".join(
            [
                f"## 对比分析：《{left_title}》 vs 《{right_title}》",
                "",
                "**对比结论：** 两份文档在关注重点上存在差异，建议结合具体业务场景进一步确认适用版本。",
                "",
                "| 主题 | 文档 A | 文档 B | 差异说明 |",
                "| --- | --- | --- | --- |",
                f"| 核心要求 | {left_text} | {right_text} | {diff} |",
                "",
                "### 使用建议",
                "1. 若需落地执行，请继续追问适用对象、审批流程或生效时间。",
                "2. 若是新旧版本对比，请补充版本年份以减少错配。",
            ]
        )

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
        if any(token in query for token in LEAVE_ALIAS_MARKERS):
            aliases.extend(["leave", "vacation", "holiday", *LEAVE_ALIAS_MARKERS])
        if any(token in query for token in TRAVEL_ALIAS_MARKERS):
            aliases.extend(["travel", "expense", "reimburse", *TRAVEL_ALIAS_MARKERS])
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

    def _select_primary_result(self, query: str, results: list[dict]) -> dict:
        if not results:
            return {}
        if not self._is_core_requirements_query(query):
            return results[0]

        def score(item: dict) -> tuple[int, float]:
            snippet = " ".join(str(item.get("snippet") or "").split()).strip()
            page_number = int(item.get("page_number") or 0)
            points = 0
            if any(marker in snippet for marker in ("总则", "适用于", "差旅费是指", "加强和规范", "定义", "基本原则")):
                points += 8
            if any(marker in snippet for marker in ("审批", "报销", "标准", "住宿费", "伙食补助费", "交通费")):
                points += 5
            if any(marker in snippet for marker in ("责任", "处分", "附则", "负责解释", "印发", "通知")):
                points -= 6
            if 2 <= page_number <= 6:
                points += 3
            if page_number >= 10:
                points -= 2
            return points, float(item.get("score") or 0.0)

        return max(results, key=score)

    def _is_core_requirements_query(self, query: str) -> bool:
        normalized = str(query or "").strip()
        return any(marker in normalized for marker in ("核心要求", "主要要求", "关键要求", "核心内容", "主要内容", "要点", "重点"))

    def _build_follow_up_hint(self, query: str, results: list[dict]) -> str:
        titles = []
        for item in results[:2]:
            title = str(item.get("document_title") or "").strip()
            if title and title not in titles:
                titles.append(title)
        if "版本" in query or "区别" in query or "差异" in query:
            return "如需进一步确认版本差异，请补充另一份制度的年份或版本号。"
        if titles:
            return f"如需继续细化，可围绕《{titles[0]}》追问适用范围、审批流程或生效时间。"
        return "如需继续细化，请补充制度名称、年份、章节或部门范围。"

    def _format_source(self, item: dict) -> str:
        title = item.get("document_title") or "未知文档"
        section = item.get("section_title") or "未命名章节"
        page = item.get("page_number")
        if page is None:
            return f"《{title}》 / {section}"
        return f"《{title}》 / 第 {page} 页 / {section}"

    def _normalize_text(self, text: str) -> str:
        snippet = " ".join((text or "").split())
        if len(snippet) > 160:
            snippet = snippet[:157].rstrip() + "..."
        return snippet

    def _is_valid_chinese_answer(self, answer: str | None) -> bool:
        if not answer:
            return False
        text = answer.strip()
        if len(text) <= 10:
            return False
        if text.count("?") >= 6 or any(marker in text for marker in GARBLED_MARKERS):
            return False
        chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        non_space = len(text.replace(" ", "").replace("\n", ""))
        return non_space > 0 and chinese_chars / non_space > 0.08
