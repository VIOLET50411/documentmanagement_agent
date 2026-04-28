"""Graph extractor with optional LLM extraction and deterministic fallback."""

from __future__ import annotations

import json
import re

import structlog

from app.retrieval.neo4j_client import Neo4jClient
from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.graph_extractor")

EXTRACTION_SYSTEM_PROMPT = """你是企业文档知识图谱构建器。请从文档片段中提取实体及其关系。
输出必须是 JSON 数组，每个元素包含以下字段：
- source: 源实体（人名、部门、制度、文档、系统等）
- relationship: 关系类型，允许值为 manages、references、amends、reports_to、related_to
- target: 目标实体

关系类型含义：
- manages: 负责、审批、管理
- references: 引用、依据、参照
- amends: 修订、替代、更新
- reports_to: 上下级、汇报关系
- related_to: 其他一般关联

只输出 JSON 数组，例如：[{"source":"A","relationship":"manages","target":"B"}]"""


class GraphExtractor:
    """Extract entities and relationships from document chunks."""

    def __init__(self):
        self._disable_llm_for_run = False

    def extract_and_store_sync(self, chunks: list[dict]) -> list[dict]:
        """Synchronous entry point for Celery tasks (no event loop required)."""
        triples = []
        llm = LLMService()
        use_llm = not llm.is_rule_only

        for chunk in chunks:
            text = chunk.get("content", "")
            if not text.strip():
                continue

            if use_llm and not self._disable_llm_for_run:
                llm_triples = self._extract_with_llm_sync(llm, text, chunk)
                if llm_triples:
                    triples.extend(llm_triples)
                    continue
                if self._disable_llm_for_run:
                    use_llm = False

            entities = self._extract_entities(text)
            triples.extend(self._extract_relationships(entities, text, chunk))

        if triples:
            client = None
            try:
                client = Neo4jClient()
                client.upsert_triples(triples)
            except Exception:
                pass
            finally:
                if client is not None:
                    client.close()
        return triples

    async def extract_and_store(self, chunks: list[dict]) -> list[dict]:
        """Async entry point (compatibility with existing code)."""
        return self.extract_and_store_sync(chunks)

    def _extract_with_llm_sync(self, llm: LLMService, text: str, chunk: dict) -> list[dict] | None:
        """Synchronous LLM extraction using httpx directly."""
        import httpx

        if llm.is_rule_only or self._disable_llm_for_run:
            return None

        try:
            payload = {
                "model": llm.model,
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"文档片段:\n{text[:800]}"},
                ],
                "temperature": 0.0,
                "max_tokens": 400,
                "stream": False,
            }
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=2.0)) as client:
                resp = client.post(llm.base_url + "/chat/completions", json=payload, headers=llm._headers())
                resp.raise_for_status()
                data = resp.json()
                content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")

            if not content:
                return None

            parsed = _parse_triples(content)
            if parsed:
                for triple in parsed:
                    triple["doc_id"] = chunk.get("doc_id")
                    triple["tenant_id"] = chunk.get("tenant_id", "default")
                    triple["section_title"] = chunk.get("section_title")
                return parsed
            return None
        except (httpx.HTTPError, OSError, RuntimeError) as exc:
            logger.debug("graph_extractor.llm_failed", error=str(exc))
            self._disable_llm_for_run = True
            return None
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            logger.debug("graph_extractor.llm_parse_failed", error=str(exc))
            return None

    def _extract_entities(self, text: str) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text)
        seen = set()
        entities = []
        for token in tokens:
            if token not in seen:
                seen.add(token)
                entities.append(token)
        return entities[:10]

    def _extract_relationships(self, entities: list[str], text: str, chunk: dict) -> list[dict]:
        relationship = "related_to"
        if any(token in text for token in ("审批", "负责", "流程", "管理")):
            relationship = "manages"
        elif any(token in text for token in ("引用", "依据", "参照", "参考")):
            relationship = "references"
        elif any(token in text for token in ("替代", "修订", "更新", "修正")):
            relationship = "amends"
        elif any(token in text for token in ("汇报", "上级", "下级")):
            relationship = "reports_to"

        triples = []
        if len(entities) == 1:
            entities = [entities[0], chunk.get("section_title") or chunk.get("doc_id") or "document"]
        for left, right in zip(entities, entities[1:]):
            triples.append(
                {
                    "source": left,
                    "relationship": relationship,
                    "target": right,
                    "doc_id": chunk.get("doc_id"),
                    "tenant_id": chunk.get("tenant_id", "default"),
                    "section_title": chunk.get("section_title"),
                }
            )
        return triples


def _parse_triples(raw: str) -> list[dict] | None:
    """Parse LLM output into triple list."""
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            valid = []
            for item in data:
                if isinstance(item, dict) and "source" in item and "target" in item:
                    valid.append(
                        {
                            "source": str(item["source"]),
                            "relationship": str(item.get("relationship", "related_to")),
                            "target": str(item["target"]),
                        }
                    )
            return valid if valid else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[[\s\S]*?\]", text)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return [
                    {
                        "source": str(item["source"]),
                        "relationship": str(item.get("relationship", "related_to")),
                        "target": str(item["target"]),
                    }
                    for item in data
                    if isinstance(item, dict) and "source" in item and "target" in item
                ] or None
        except json.JSONDecodeError:
            pass

    return None
