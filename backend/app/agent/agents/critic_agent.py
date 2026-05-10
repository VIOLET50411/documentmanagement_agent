"""Critic agent: LLM-based answer review with deterministic fallback."""

from __future__ import annotations

import json

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.critic_agent")

CRITIC_SYSTEM_PROMPT = """你是企业文档问答系统的审查员。请检查 AI 生成的回答是否满足：
1. 结论是否有证据支撑；
2. 引用是否足够；
3. 是否出现与证据矛盾或超出证据的信息；
4. 是否需要提示“证据不足”。
仅输出 JSON，例如：{"approved": true, "reason": "审查说明"}"""


class CriticAgent:
    """Review responses from specialist agents before output."""

    async def run(self, state: dict) -> dict:
        answer = (state.get("answer") or "").strip()
        citations = state.get("citations") or []

        if not answer:
            state["critic_approved"] = False
            state["iteration"] = state.get("iteration", 0) + 1
            state["answer"] = "当前没有生成有效答案。"
            return state

        if state.get("agent_used") in {"compliance", "summary", "graph"} and not citations:
            state["critic_approved"] = False
            state["iteration"] = state.get("iteration", 0) + 1
            state["answer"] = "已命中相关内容，但缺少可引用依据，当前不输出无出处结论。"
            return state

        structure_issue = self._validate_structure(state, answer)
        if structure_issue:
            state["critic_approved"] = False
            state["critic_source"] = "rule_structure"
            state["critic_reason"] = structure_issue
            state["iteration"] = state.get("iteration", 0) + 1
            state["answer"] = f"{answer}\n\n审查提示：{structure_issue}"
            return state

        llm = LLMService()
        if not llm.is_rule_only and len(answer) > 20:
            try:
                query = state.get("rewritten_query") or state.get("query") or ""
                evidence_snippets = "\n".join(
                    f"- {c.get('doc_title', '未知文档')}: {c.get('snippet', '')[:200]}"
                    for c in citations[:5]
                )
                user_prompt = (
                    f"用户问题：{query}\n\n"
                    f"AI 回答：\n{answer[:1000]}\n\n"
                    f"文档证据：\n{evidence_snippets or '无引用'}"
                )
                result = await llm.generate(
                    system_prompt=CRITIC_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.0,
                    max_tokens=200,
                )
                if result:
                    decision = _parse_critic_decision(result)
                    state["critic_approved"] = decision["approved"]
                    state["critic_reason"] = decision.get("reason", "")
                    state["critic_source"] = "llm"
                    if not decision["approved"]:
                        state["iteration"] = state.get("iteration", 0) + 1
                        state["answer"] = f"{answer}\n\n审查提示：{decision.get('reason', '未通过审查')}"
                        logger.info("critic.llm_revision", reason=decision.get("reason", ""))
                    return state
            except Exception as exc:  # noqa: BLE001
                logger.warning("critic.llm_failed", error=str(exc))

        state["critic_approved"] = True
        state["critic_source"] = "rule_fallback"
        return state

    def _validate_structure(self, state: dict, answer: str) -> str | None:
        agent_used = str(state.get("agent_used") or "").strip()
        intent = str(state.get("intent") or "").strip()

        if agent_used == "summary" and "### 关键要点" not in answer:
            return "摘要回答缺少“关键要点”结构，当前要求重新整理。"
        if agent_used == "compliance" and intent == "qa" and "**结论：**" not in answer:
            return "制度问答缺少明确结论，当前要求重新整理。"
        if intent == "compare" and "| 主题 | 文档 A | 文档 B | 差异说明 |" not in answer and "无法完成可靠对比" not in answer:
            return "对比回答缺少差异表或澄清提示，当前要求重新整理。"
        return None


def _parse_critic_decision(raw: str) -> dict:
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "approved" in data:
            return {"approved": bool(data["approved"]), "reason": str(data.get("reason", ""))}
    except json.JSONDecodeError:
        pass

    lowered = text.lower()
    if "approved" in lowered or "通过" in lowered:
        return {"approved": True, "reason": text[:200]}
    if "revision" in lowered or "不通过" in lowered or "修改" in lowered:
        return {"approved": False, "reason": text[:200]}
    return {"approved": True, "reason": "unable to parse critic output"}
