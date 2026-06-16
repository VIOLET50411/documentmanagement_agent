"""Critic agent: multi-dimensional quality review with improvement hints."""

from __future__ import annotations

import json
import re

import structlog

from app.agent.prompts.system import CRITIC_SYSTEM_PROMPT
from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.critic_agent")


class CriticAgent:
    """Review responses from specialist agents with multi-dimensional scoring."""

    async def run(self, state: dict) -> dict:
        answer = (state.get("answer") or "").strip()
        citations = state.get("citations") or []

        # 如果 generator 已经给出了「未找到」的模板回答，直接放行
        # 不再做 LLM 审查和重试，避免无意义循环
        generation_source = state.get("generation_source") or ""
        if generation_source in ("irrelevant_guard", "empty", "general_knowledge"):
            state["critic_approved"] = True
            state["critic_source"] = "passthrough"
            return state

        if not answer:
            state["critic_approved"] = False
            state["iteration"] = state.get("iteration", 0) + 1
            state["answer"] = "当前没有生成有效答案。"
            state["critic_improvement_hint"] = "需要生成一个有效的回答"
            return state

        if state.get("agent_used") in {"compliance", "summary", "graph"} and not citations:
            state["critic_approved"] = False
            state["iteration"] = state.get("iteration", 0) + 1
            state["answer"] = "已命中相关内容，但缺少可引用依据，当前不输出无出处结论。"
            state["critic_improvement_hint"] = "回答缺少引用来源，需要在回答中关联具体的文档证据"
            return state

        # 篇幅检查：LLM 生成的回答不应太短
        generation_source = state.get("generation_source") or ""
        if generation_source in ("llm",) and len(answer) < 150:
            state["critic_approved"] = False
            state["critic_source"] = "rule_length"
            state["critic_reason"] = "回答篇幅不足"
            state["critic_improvement_hint"] = (
                "当前回答过于简短（仅 {} 字）。请充分展开论述：\n"
                "1. 增加制度依据的引用和具体条款内容\n"
                "2. 补充适用条件、例外情况和注意事项\n"
                "3. 增加实务操作建议\n"
                "4. 目标篇幅：300 字以上"
            ).format(len(answer))
            state["iteration"] = state.get("iteration", 0) + 1
            logger.info("critic.length_reject", answer_len=len(answer))
            return state

        # 结构验证
        structure_issue = self._validate_structure(state, answer)
        if structure_issue:
            state["critic_approved"] = False
            state["critic_source"] = "rule_structure"
            state["critic_reason"] = structure_issue
            state["critic_improvement_hint"] = structure_issue
            state["iteration"] = state.get("iteration", 0) + 1
            state["critic_notes"] = structure_issue
            return state

        # LLM 多维度审查
        llm = LLMService()
        if not llm.is_rule_only and len(answer) > 20:
            try:
                query = state.get("rewritten_query") or state.get("query") or ""
                evidence_snippets = "\n".join(
                    f"- 《{c.get('doc_title', '未知文档')}》: {c.get('snippet', '')[:300]}"
                    for c in citations[:8]
                )
                user_prompt = (
                    f"## 用户问题\n{query}\n\n"
                    f"## AI 回答（{len(answer)} 字）\n{answer[:2000]}\n\n"
                    f"## 文档证据\n{evidence_snippets or '无引用'}\n\n"
                    f"## 请进行多维度审查并输出 JSON"
                )
                result = await llm.generate(
                    system_prompt=CRITIC_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.0,
                    max_tokens=400,
                )
                if result:
                    decision = _parse_critic_decision(result)
                    state["critic_approved"] = decision["approved"]
                    state["critic_reason"] = decision.get("reason", "")
                    state["critic_source"] = "llm"
                    state["critic_scores"] = decision.get("scores", {})
                    state["critic_weakest_dimension"] = decision.get("weakest_dimension", "")

                    if not decision["approved"]:
                        state["iteration"] = state.get("iteration", 0) + 1
                        state["critic_notes"] = decision.get("reason", "")
                        # 将改进方向传递给 generator 重试
                        hint = decision.get("improvement_hint", "")
                        weakest = decision.get("weakest_dimension", "")
                        if not hint and weakest:
                            hint = _generate_improvement_hint(weakest, decision.get("scores", {}))
                        state["critic_improvement_hint"] = hint
                        logger.info(
                            "critic.llm_revision",
                            reason=decision.get("reason", ""),
                            weakest=weakest,
                            scores=decision.get("scores", {}),
                        )
                    return state
            except Exception as exc:  # noqa: BLE001
                logger.warning("critic.llm_failed", error=str(exc))

        state["critic_approved"] = True
        state["critic_source"] = "rule_fallback"
        return state

    def _validate_structure(self, state: dict, answer: str) -> str | None:
        """Validate answer structure based on agent type and intent."""
        agent_used = str(state.get("agent_used") or "").strip()
        intent = str(state.get("intent") or "").strip()

        # 摘要回答的结构检查放宽（LLM 摘要格式可能不同）
        if agent_used == "summary" and state.get("generation_source") != "llm":
            if "关键要点" not in answer and "关键" not in answer:
                return "摘要回答缺少关键要点结构，请增加关键要点总结。"

        # 对比回答需要有对比结构
        if intent == "compare":
            has_table = "|" in answer and "---" in answer
            has_comparison = any(kw in answer for kw in ("对比", "差异", "区别", "不同", "相比"))
            has_disclaimer = "无法完成可靠对比" in answer
            if not has_table and not has_comparison and not has_disclaimer:
                return "对比回答缺少对比分析结构（表格或差异说明），请补充。"

        return None


def _generate_improvement_hint(weakest_dimension: str, scores: dict) -> str:
    """根据最弱维度生成具体的改进提示。"""
    hints = {
        "faithfulness": (
            "回答中存在与文档证据不一致的内容。请：\n"
            "1. 删除所有无法在文档中找到依据的陈述\n"
            "2. 确保每个关键论点都能对应到具体的文档片段\n"
            "3. 对不确定的内容使用「根据现有文档」等限定表达"
        ),
        "completeness": (
            "回答不够完整。请：\n"
            "1. 检查是否遗漏了用户问题的某些方面\n"
            "2. 补充重要的条件、限制和例外情况\n"
            "3. 增加实务操作的具体步骤和注意事项\n"
            "4. 回答篇幅应不少于 300 字"
        ),
        "relevance": (
            "回答包含了过多与问题无关的内容。请：\n"
            "1. 删除与用户问题不直接相关的段落\n"
            "2. 聚焦在用户真正想了解的核心问题上\n"
            "3. 确保每个段落都在回应用户的问题"
        ),
        "citation_accuracy": (
            "引用不够准确或完整。请：\n"
            "1. 检查引用的文档标题和章节是否与原文一致\n"
            "2. 确保关键结论都有对应的文档来源\n"
            "3. 在论述中更明确地指出信息出自哪个文档"
        ),
    }
    return hints.get(weakest_dimension, "请根据审查反馈改进回答质量。")


def _parse_critic_decision(raw: str) -> dict:
    """Parse LLM multi-dimensional critic output."""
    text = raw.strip()

    # 尝试提取 JSON
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if isinstance(data, dict) and "approved" in data:
                scores = data.get("scores", {})
                # 如果有多维度评分，根据最低分判断是否通过
                if scores:
                    min_score = min(scores.values()) if scores else 1.0
                    approved = min_score >= 0.7
                else:
                    approved = bool(data["approved"])

                return {
                    "approved": approved,
                    "scores": scores,
                    "weakest_dimension": str(data.get("weakest_dimension", "")),
                    "reason": str(data.get("reason", "")),
                    "improvement_hint": str(data.get("improvement_hint", "")),
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 文本回退
    lowered = text.lower()
    if "approved" in lowered or "通过" in lowered:
        return {"approved": True, "reason": text[:200], "scores": {}, "weakest_dimension": "", "improvement_hint": ""}
    if "revision" in lowered or "不通过" in lowered or "修改" in lowered:
        return {"approved": False, "reason": text[:200], "scores": {}, "weakest_dimension": "", "improvement_hint": text[:200]}
    return {"approved": True, "reason": "unable to parse critic output", "scores": {}, "weakest_dimension": "", "improvement_hint": ""}
