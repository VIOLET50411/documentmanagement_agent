"""Self-correction node: retrieval quality assessment with smart retry strategy."""

from __future__ import annotations

import json
import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.self_correction")

SELF_CORRECTION_SYSTEM_PROMPT = """\
你是一位专业的检索质量评估专家。请判断检索到的文档片段是否足以回答用户的问题。

## 评估维度

1. **相关性**：片段内容是否与用户问题直接相关？
2. **完整性**：片段信息是否足以支撑一个完整、详尽的回答？
3. **准确性**：片段来源是否权威可靠（正式制度文件 vs 非正式材料）？
4. **缺口分析**：如果不足，缺少什么类型的信息？

## 输出格式
输出严格的 JSON：
{
  "sufficient": true/false,
  "confidence": 0.0-1.0,
  "reason": "评估说明",
  "missing_info_type": "缺少的信息类型（如：具体条款、审批流程、金额标准等）",
  "suggestion": "改进建议（换什么关键词、调整什么检索策略）",
  "retry_query": "如果不足，建议的补充检索查询"
}"""


async def self_correction(state: dict) -> dict:
    """Validate retrieval quality and decide if re-retrieval is needed."""
    state["iteration"] = state.get("iteration", 0) + 1
    docs = state.get("retrieved_docs") or []
    query = state.get("rewritten_query") or state.get("query") or ""

    if not docs:
        state["retrieval_sufficient"] = False
        state["self_correction_reason"] = "no_results"
        state["self_correction_source"] = "empty"
        state["retry_strategy"] = {"action": "broaden_query", "hint": "尝试使用更宽泛的关键词"}
        return state

    llm = LLMService()
    if not llm.is_rule_only and docs:
        try:
            # 构建更丰富的检索证据展示
            evidence_lines = []
            for idx, item in enumerate(docs[:8], start=1):
                title = item.get("document_title") or "未知"
                section = item.get("section_title") or ""
                snippet = (item.get("snippet") or "")[:300]
                score = item.get("score", 0.0)
                evidence_lines.append(
                    f"[{idx}] 《{title}》 {section} (相关度:{score:.2f})\n{snippet}"
                )

            result = await llm.generate(
                system_prompt=SELF_CORRECTION_SYSTEM_PROMPT,
                user_prompt=(
                    f"## 用户问题\n{query}\n\n"
                    f"## 检索到的文档片段（共 {len(docs)} 条）\n\n"
                    + "\n\n".join(evidence_lines)
                ),
                temperature=0.0,
                max_tokens=300,
            )
            if result:
                decision = _parse_decision(result)
                state["retrieval_sufficient"] = decision["sufficient"]
                state["self_correction_reason"] = decision.get("reason", "llm_assessed")
                state["self_correction_source"] = "llm"
                state["self_correction_confidence"] = decision.get("confidence", 0.5)

                # 构建重试策略
                if not decision["sufficient"]:
                    retry_query = decision.get("retry_query", "")
                    missing_type = decision.get("missing_info_type", "")
                    state["retry_strategy"] = {
                        "action": "refine_query",
                        "retry_query": retry_query,
                        "missing_info_type": missing_type,
                        "hint": decision.get("suggestion", ""),
                    }
                    # 注意：不自动覆盖 rewritten_query，避免 LLM 生成的
                    # retry_query 质量不可控导致后续检索偏离用户意图

                return state
        except Exception as exc:  # noqa: BLE001
            logger.warning("self_correction.llm_failed", error=str(exc))

    # Rule-based fallback with stop-word filtering
    _SELF_CORRECTION_STOP_WORDS = {
        "的", "了", "在", "是", "有", "和", "与", "对", "为", "中",
        "什么", "哪些", "怎么", "如何", "当前", "需要", "应该",
        "管理", "制度", "办法", "规定", "相关", "情况", "问题",
        "平台", "系统", "处理", "工作", "单位", "部门", "请",
        "列出", "说明", "给出", "优先", "原因", "可以", "进行",
    }
    text = " ".join(
        f"{item.get('document_title', '')} {item.get('section_title', '') or ''} {item.get('snippet', '')}"
        for item in docs[:5]
    )
    query_terms = [
        t for t in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", query)
        if t not in _SELF_CORRECTION_STOP_WORDS
    ]
    if not query_terms:
        state["retrieval_sufficient"] = True
        state["self_correction_reason"] = "generic_query_passthrough"
        state["self_correction_source"] = "rule_fallback"
        return state

    overlap = sum(1 for token in query_terms if token and token in text)
    overlap_ratio = overlap / len(query_terms) if query_terms else 0
    min_overlap = max(1, len(query_terms) * 3 // 10)  # require >= 30% term overlap

    state["retrieval_sufficient"] = overlap >= min_overlap
    state["self_correction_reason"] = "accepted" if state["retrieval_sufficient"] else "low_overlap"
    state["self_correction_source"] = "rule_fallback"
    state["self_correction_confidence"] = round(overlap_ratio, 2)

    if not state["retrieval_sufficient"]:
        # 分析未匹配的关键词，构建补充查询建议
        missing_terms = [t for t in query_terms if t not in text]
        state["retry_strategy"] = {
            "action": "refine_query",
            "missing_terms": missing_terms[:5],
            "hint": f"以下关键词未在检索结果中出现：{'、'.join(missing_terms[:3])}",
        }

    return state


def _parse_decision(raw: str) -> dict:
    """Parse LLM self-correction output."""
    text = raw.strip()

    # 尝试提取 JSON
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if isinstance(data, dict) and "sufficient" in data:
                return {
                    "sufficient": bool(data["sufficient"]),
                    "confidence": float(data.get("confidence", 0.5)),
                    "reason": str(data.get("reason", "")),
                    "missing_info_type": str(data.get("missing_info_type", "")),
                    "suggestion": str(data.get("suggestion", "")),
                    "retry_query": str(data.get("retry_query", "")),
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 文本回退
    lowered = text.lower()
    sufficient = "sufficient" in lowered or "充分" in lowered or "足够" in lowered
    return {
        "sufficient": sufficient,
        "confidence": 0.6 if sufficient else 0.3,
        "reason": text[:200],
        "missing_info_type": "",
        "suggestion": "",
        "retry_query": "",
    }
