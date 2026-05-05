"""Graph extractor with optional LLM extraction and deterministic fallback."""

from __future__ import annotations

import json
import re

import structlog

from app.retrieval.neo4j_client import Neo4jClient
from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.graph_extractor")

GENERIC_ENTITY_TERMS = {
    "关于印发",
    "的通知",
    "各单位",
    "特此通知",
    "第一章",
    "第二章",
    "第三章",
    "第四章",
    "第五章",
    "第一条",
    "第二条",
    "第三条",
    "第四条",
    "第五条",
    "第六条",
    "第七条",
    "第八条",
    "第九条",
    "第十条",
    "修订",
    "试行",
    "根据",
    "西校",
    "我校",
    "其中",
    "总则",
    "基本情况",
    "现印发给你们",
    "请遵照执行",
    "日印发",
    "年第",
    "附件",
    "依据",
    "单位",
    "管理",
    "价值",
    "办法",
    "万元",
    "元以上",
    "学校基本情况",
    "结合学校实际",
    "科目名称",
    "名词解释",
    "事业收入",
    "其他收入",
    "教育",
    "专用设",
    "十一",
    "个月",
    "西南大学文",
    "次校",
    "次校长办",
    "已经学校2018",
    "财教",
    "专款专用",
    "双一流",
    "按照",
    "审批",
    "归口管理",
    "基本建",
    "建设高",
    "责任到",
    "主要职责是",
    "从其规定",
    "有关规定",
    "留归学校",
    "纳入学校预算",
    "统一管理",
    "统一领导",
    "审议",
    "安全",
    "手续",
    "法规",
    "资产",
    "项目",
    "由学校",
    "修编",
    "报教育部",
    "设计",
}

ENTITY_SUFFIX_HINTS = (
    "大学",
    "学院",
    "学校",
    "部门",
    "单位",
    "小组",
    "办公室",
    "中心",
    "处",
    "部",
    "馆",
    "办法",
    "制度",
    "规范",
    "规则",
    "流程",
    "项目",
    "预算",
    "资金",
    "资产",
    "合同",
    "采购",
    "报销",
)

FRAGMENT_MARKERS = (
    "印发",
    "执行",
    "研究通过",
    "提高",
    "维护",
    "优化",
    "盘活",
    "规范",
    "加强",
    "负责",
    "结合学校实际",
    "基本情况",
    "办公会",
)

PHRASE_FRAGMENT_MARKERS = (
    "相结合",
    "另有规定",
    "每月",
    "每季度",
    "学校实行",
    "使用单位于",
    "同时废止",
    "应根据",
    "应执行",
    "工作日报",
    "工作日内",
    "报教育部备案",
    "报教育部审核",
    "报财政部备案",
    "审核后报",
    "履行审批手续",
    "按以下权限",
    "原则上不予",
)

ENTITY_SPLIT_MARKERS = (
    "负责",
    "审批",
    "审核",
    "管理",
    "流程",
    "备案",
    "归口",
)

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
            if self._should_skip_chunk(text, chunk):
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
            candidates = [token]
            if not self._is_valid_entity(token):
                candidates = self._split_entity_candidates(token)
            for candidate in candidates:
                if not self._is_valid_entity(candidate):
                    continue
                if candidate not in seen:
                    seen.add(candidate)
                    entities.append(candidate)
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
            fallback = self._fallback_entity(chunk)
            if not fallback or fallback == entities[0]:
                return []
            entities = [entities[0], fallback]
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

    def _is_valid_entity(self, token: str) -> bool:
        normalized = str(token or "").strip()
        if len(normalized) < 2:
            return False
        if normalized in GENERIC_ENTITY_TERMS:
            return False
        if re.fullmatch(r"\d{2,}", normalized):
            return False
        if re.fullmatch(r"第[一二三四五六七八九十百千万0-9]+[章节条款项]", normalized):
            return False
        if re.fullmatch(r"[0-9]{4}年?", normalized):
            return False
        if re.fullmatch(r"[年月日0-9]{2,}", normalized):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?万?元(?:以上)?", normalized):
            return False
        if re.fullmatch(r"(?:\d+(?:\.\d+)?)?万?元(?:以下|以上|以内)", normalized):
            return False
        if re.fullmatch(r"[一二三四五六七八九十百千万]+", normalized):
            return False
        if re.fullmatch(r"西校〔?\d{4}〕?\d+号", normalized):
            return False
        if normalized.startswith(("西南大学文", "次校", "财教", "已经学校")):
            return False
        if normalized.startswith("对于") and len(normalized) >= 8:
            return False
        if self._looks_like_fragment(normalized):
            return False
        return True

    def _fallback_entity(self, chunk: dict) -> str | None:
        candidates = [
            chunk.get("title"),
            chunk.get("section_title"),
            chunk.get("doc_id"),
        ]
        for item in candidates:
            normalized = str(item or "").strip()
            if self._is_valid_entity(normalized):
                return normalized
        return None

    def _looks_like_fragment(self, token: str) -> bool:
        if any(marker in token for marker in FRAGMENT_MARKERS):
            return True
        if any(marker in token for marker in PHRASE_FRAGMENT_MARKERS):
            return True
        if "工作日" in token or token.endswith(("备案", "审核")):
            return True
        if len(token) >= 6 and any(char in token for char in ("与", "于", "已", "应", "按", "并")):
            return True
        if len(token) >= 6 and token.startswith(("由", "经", "按", "应", "对", "每")):
            return True
        if token.startswith(("为", "按", "将", "请", "现")) and len(token) >= 4:
            return True
        if token.endswith(("你们", "执行", "通过", "效益", "权益")):
            return True
        if any(token.endswith(suffix) for suffix in ENTITY_SUFFIX_HINTS):
            return False
        return False

    def _should_skip_chunk(self, text: str, chunk: dict) -> bool:
        content_type = str(chunk.get("content_type") or "").lower()
        if content_type == "table":
            return True

        normalized = str(text or "").strip()
        if not normalized:
            return True

        table_markers = (
            "单位：万元",
            "科目编码",
            "科目名称",
            "支出预算表",
            "收入预算表",
            "政府采购目录",
            "预算金额",
        )
        if any(marker in normalized for marker in table_markers):
            return True

        number_groups = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", normalized)
        cjk_tokens = re.findall(r"[\u4e00-\u9fffA-Za-z]{2,}", normalized)
        if len(number_groups) >= 8 and len(cjk_tokens) <= len(number_groups):
            return True

        return False

    def _split_entity_candidates(self, token: str) -> list[str]:
        normalized = str(token or "").strip()
        if not normalized:
            return []

        candidates: list[str] = []
        for marker in ENTITY_SPLIT_MARKERS:
            if marker not in normalized:
                continue
            prefix, suffix = normalized.split(marker, 1)
            prefix = prefix.strip("：:、，,（）() ")
            suffix = suffix.strip("：:、，,（）() ")
            if prefix and any(prefix.endswith(hint) for hint in ENTITY_SUFFIX_HINTS):
                candidates.append(prefix)
            if suffix and any(suffix.endswith(hint) for hint in ENTITY_SUFFIX_HINTS):
                candidates.append(suffix)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if len(candidate) < 2 or candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped


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
