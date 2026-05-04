"""LLM-assisted QA pair generator for SFT training data."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

logger = structlog.get_logger("docmind.qa_generator")


class QAGenerator:
    """Generate multi-angle QA pairs from document chunks using LLM."""

    PROMPT_TEMPLATES = {
        "policy": (
            "基于以下管理制度内容，生成3个员工可能会问的问题及准确回答。\n"
            "要求：问题应覆盖适用范围、核心要求、执行标准三个角度。\n"
            "输出JSON数组格式：[{\"question\": \"...\", \"answer\": \"...\"}]"
        ),
        "approval": (
            "基于以下审批流程，生成3个关于审批条件、权限、时限的问答。\n"
            "要求：问题应具体，答案应包含具体条件和数值。\n"
            "输出JSON数组格式：[{\"question\": \"...\", \"answer\": \"...\"}]"
        ),
        "compliance": (
            "基于以下合规要求，生成3个合规判断场景问答。\n"
            "要求：问题以'是否合规'或'如何处理'开头，答案引用具体条款。\n"
            "输出JSON数组格式：[{\"question\": \"...\", \"answer\": \"...\"}]"
        ),
        "hr": (
            "基于以下人事制度，生成3个员工日常咨询问答。\n"
            "要求：问题应贴近实际场景（请假、考勤、福利等）。\n"
            "输出JSON数组格式：[{\"question\": \"...\", \"answer\": \"...\"}]"
        ),
        "finance": (
            "基于以下财务制度，生成3个关于报销标准和审批权限的问答。\n"
            "要求：答案应包含金额限制、审批层级等具体信息。\n"
            "输出JSON数组格式：[{\"question\": \"...\", \"answer\": \"...\"}]"
        ),
        "general": (
            "基于以下文档内容，生成3个多角度问答对。\n"
            "要求：问题应具体明确，答案完整准确。\n"
            "输出JSON数组格式：[{\"question\": \"...\", \"answer\": \"...\"}]"
        ),
    }

    SYSTEM_PROMPT = (
        "你是企业训练数据生成助手。根据提供的文档内容生成高质量问答对，"
        "用于微调企业文档问答模型。要求：\n"
        "1. 问题自然、具体、贴近真实使用场景\n"
        "2. 答案准确、完整，基于文档内容\n"
        "3. 严格输出JSON数组格式"
    )

    def __init__(self, max_chunk_chars: int = 1500):
        self.max_chunk_chars = max_chunk_chars

    async def generate_qa_pairs(
        self,
        chunk_content: str,
        doc_type: str,
        doc_title: str,
    ) -> list[dict[str, str]]:
        """Generate QA pairs for a document chunk using LLM."""
        from app.services.llm_service import LLMService

        template = self.PROMPT_TEMPLATES.get(doc_type, self.PROMPT_TEMPLATES["general"])
        user_prompt = f"{template}\n\n文档标题：{doc_title}\n内容：{chunk_content[:self.max_chunk_chars]}"

        try:
            raw = await LLMService().generate(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=1000,
            )
            return self._parse_qa_pairs(raw)
        except Exception as exc:
            logger.warning("qa_generator.llm_failed", error=str(exc), doc_title=doc_title)
            return []

    def _parse_qa_pairs(self, raw_text: str) -> list[dict[str, str]]:
        """Parse LLM output into structured QA pairs."""
        # Try direct JSON parse
        try:
            data = json.loads(raw_text)
            if isinstance(data, list):
                return [
                    {"question": str(item["question"]), "answer": str(item["answer"])}
                    for item in data
                    if isinstance(item, dict) and "question" in item and "answer" in item
                ]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Try to extract JSON array from markdown code block
        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    return [
                        {"question": str(item["question"]), "answer": str(item["answer"])}
                        for item in data
                        if isinstance(item, dict) and "question" in item and "answer" in item
                    ]
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # Try to find JSON array anywhere in the text
        match = re.search(r"\[.*?\]", raw_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return [
                        {"question": str(item["question"]), "answer": str(item["answer"])}
                        for item in data
                        if isinstance(item, dict) and "question" in item and "answer" in item
                    ]
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        return []


class NegativeSampleGenerator:
    """Generate negative (out-of-scope) SFT samples to teach refusal."""

    REFUSAL_ANSWER = (
        "根据已有企业文档，暂无法找到与该问题直接相关的制度规定。"
        "建议联系相关部门确认。"
    )

    OUT_OF_SCOPE_TEMPLATES = [
        "请问公司的{topic}政策是什么？",
        "关于{topic}方面有什么规定吗？",
        "{topic}的具体流程是怎样的？",
        "公司对{topic}有什么要求？",
    ]

    UNRELATED_TOPICS = [
        "竞品分析", "市场营销策略", "产品定价", "股权激励",
        "海外拓展", "并购重组", "专利申请", "法律诉讼",
        "供应链金融", "碳中和", "ESG报告", "投资者关系",
    ]

    def generate(self, system_prompt: str, count: int = 10) -> list[dict]:
        """Generate negative SFT samples that teach the model to refuse gracefully."""
        import random

        samples = []
        topics = random.sample(self.UNRELATED_TOPICS, min(count, len(self.UNRELATED_TOPICS)))
        templates = self.OUT_OF_SCOPE_TEMPLATES

        for topic in topics:
            template = random.choice(templates)
            question = template.format(topic=topic)
            samples.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": self.REFUSAL_ANSWER},
                ]
            })
        return samples
