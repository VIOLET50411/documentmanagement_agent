"""Self-correction node: retrieval quality assessment with fallback."""

from __future__ import annotations

import json
import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.self_correction")

SELF_CORRECTION_SYSTEM_PROMPT = """你是检索质量评估器。判断检索到的文档片段是否足以回答用户问题。
评估标准：
1. 片段是否包含与问题直接相关的信息；
2. 证据是否足以支持完整回答；
3. 是否需要补充检索。

仅输出 JSON：{"sufficient": true/false, "reason": "评估说明", "suggestion": "改进建议，可选"}"""


async def self_correction(state: dict) -> dict:
    """Validate retrieval quality and decide if re-retrieval is needed."""
    state["iteration"] = state.get("iteration", 0) + 1
    docs = state.get("retrieved_docs") or []
    query = state.get("rewritten_query") or state.get("query") or ""

    if not docs:
        state["retrieval_sufficient"] = False
        state["self_correction_reason"] = "no_results"
        return state

    llm = LLMService()
    if not llm.is_rule_only and docs:
        try:
            evidence = "\n".join(
                f"- {item.get('document_title', '未知')}: {(item.get('snippet') or '')[:200]}"
                for item in docs[:5]
            )
            result = await llm.generate(
                system_prompt=SELF_CORRECTION_SYSTEM_PROMPT,
                user_prompt=f"用户问题：{query}\n\n检索到的文档片段：\n{evidence}",
                temperature=0.0,
                max_tokens=150,
            )
            if result:
                decision = _parse_decision(result)
                state["retrieval_sufficient"] = decision["sufficient"]
                state["self_correction_reason"] = decision.get("reason", "llm_assessed")
                state["self_correction_source"] = "llm"
                if decision.get("suggestion"):
                    state["retrieval_suggestion"] = decision["suggestion"]
                return state
        except Exception as exc:  # noqa: BLE001
            logger.warning("self_correction.llm_failed", error=str(exc))

    text = " ".join(
        f"{item.get('document_title', '')} {item.get('section_title', '') or ''} {item.get('snippet', '')}"
        for item in docs[:3]
    )
    query_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", query)
    overlap = sum(1 for token in query_terms if token and token in text)
    state["retrieval_sufficient"] = overlap > 0 or bool(docs)
    state["self_correction_reason"] = "accepted" if state["retrieval_sufficient"] else "low_overlap"
    state["self_correction_source"] = "rule_fallback"
    return state


def _parse_decision(raw: str) -> dict:
    """Parse LLM self-correction output."""
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "sufficient" in data:
            return {
                "sufficient": bool(data["sufficient"]),
                "reason": str(data.get("reason", "")),
                "suggestion": str(data.get("suggestion", "")),
            }
    except json.JSONDecodeError:
        pass

    lowered = text.lower()
    sufficient = "sufficient" in lowered or "充分" in lowered or "足够" in lowered
    return {"sufficient": sufficient, "reason": text[:200], "suggestion": ""}
