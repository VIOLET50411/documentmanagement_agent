"""Summarizer tool with LLM-based summarization and extractive fallback."""

from __future__ import annotations

import re

import structlog

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.summarizer")

SUMMARY_SYSTEM_PROMPT = """你是企业文档摘要助手。请根据输入文本生成结构化摘要。
输出格式根据 style 参数决定：
- executive: 一段 50-100 字的简洁概述
- bullet_points: 3-5 条关键要点列表
- detailed: 包含“概述”“关键要点”“执行建议”三部分的完整摘要"""


class Summarizer:
    """Document summarization tool with LLM support."""

    async def summarize(self, text: str, style: str = "executive") -> str:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return "当前没有可供摘要的文本。"

        llm = LLMService()
        if not llm.is_rule_only:
            try:
                style_instruction = {
                    "executive": "请输出 50-100 字的精简概述。",
                    "bullet_points": "请输出 3-5 条要点，每条以 - 开头。",
                    "detailed": "请输出包含“概述”“关键要点”“执行建议”三部分的完整摘要。",
                }.get(style, "请输出简洁摘要。")

                result = await llm.generate(
                    system_prompt=SUMMARY_SYSTEM_PROMPT,
                    user_prompt=f"摘要风格：{style_instruction}\n\n待摘要文本：\n{cleaned[:2000]}",
                    temperature=0.15,
                    max_tokens=500,
                )
                if result and len(result.strip()) > 10:
                    logger.info("summarizer.llm_ok", style=style, chars=len(result))
                    return result.strip()
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                logger.warning("summarizer.llm_failed", error=str(exc))

        sentences = [part.strip() for part in re.split(r"[。；！？\n]", cleaned) if part.strip()]
        if not sentences:
            sentences = [cleaned]

        if style == "bullet_points":
            return "\n".join(f"- {sentence}" for sentence in sentences[:5])
        if style == "detailed":
            return "；".join(sentences[:6])
        return sentences[0][:200]