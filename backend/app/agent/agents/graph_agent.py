"""Graph agent with relationship analysis and graceful fallback."""

from __future__ import annotations

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.graph_agent")

GRAPH_SYSTEM_PROMPT = """你是企业文档知识图谱分析助手。请根据检索到的实体关系信息回答用户问题。
你需要：
1. 分析实体之间的关系链路，例如审批链、引用链、修订链；
2. 用清晰语言描述关系结构；
3. 标注信息来源。
可用关系类型：
- references: 引用关系
- amends: 修订或替代关系
- manages: 负责或审批关系
- reports_to: 上下级或汇报关系
- related_to: 一般关联关系"""


class GraphAgent:
    """Specialist agent for cross-document entity relationship queries."""

    RELATIONSHIP_LABELS = {
        "references": "引用关系",
        "amends": "修订或替代关系",
        "manages": "负责或审批关系",
        "reports_to": "上下级或汇报关系",
        "related_to": "关联关系",
    }

    async def run(self, state: dict) -> dict:
        from app.retrieval.graph_searcher import GraphSearcher

        searcher = GraphSearcher()
        graph_results = await searcher.traverse(
            state.get("rewritten_query") or state["query"],
            user=state["current_user"],
            db=state["db"],
            top_k=5,
        )
        state["graph_result"] = graph_results
        state["citations"] = [
            {
                "doc_id": item["doc_id"],
                "doc_title": item["document_title"],
                "page_number": item.get("page_number"),
                "section_title": item.get("section_title"),
                "snippet": item.get("snippet", ""),
                "relevance_score": item.get("score", 0.0),
            }
            for item in graph_results
        ]

        if not graph_results:
            state["answer"] = "当前未检索到明确的关系链路，请补充制度名称、角色名称或审批动作后重试。"
            state["agent_used"] = "graph"
            return state

        llm = LLMService()
        if not llm.is_rule_only:
            try:
                query = state.get("rewritten_query") or state.get("query") or ""
                evidence = "\n".join(
                    f"- {item.get('document_title', '未知文档')} ({self.RELATIONSHIP_LABELS.get(item.get('relationship'), '关联关系')}): "
                    f"{(item.get('snippet') or '')[:300]}"
                    for item in graph_results[:5]
                )
                result = await llm.generate(
                    system_prompt=GRAPH_SYSTEM_PROMPT,
                    user_prompt=f"用户问题：{query}\n\n图谱检索结果：\n{evidence}",
                    temperature=0.15,
                    max_tokens=600,
                )
                if result and len(result.strip()) > 10:
                    state["answer"] = result.strip()
                    state["agent_used"] = "graph"
                    return state
            except Exception as exc:  # noqa: BLE001
                logger.warning("graph_agent.llm_failed", error=str(exc))

        top = graph_results[0]
        top_label = self.RELATIONSHIP_LABELS.get(top.get("relationship"), "关联关系")
        lines = [
            f"关系结论：当前最可能命中的业务关系是“{top_label}”。",
            f"核心片段：{top.get('snippet', '')}",
            "",
            "引用：",
        ]
        for index, item in enumerate(graph_results[:3], start=1):
            label = self.RELATIONSHIP_LABELS.get(item.get("relationship"), "关联关系")
            lines.append(f"{index}. 《{item.get('document_title', '未知文档')}》 / {label}")

        state["answer"] = "\n".join(lines)
        state["agent_used"] = "graph"
        return state
