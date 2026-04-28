"""Text2SQL tool with controlled SQL generation and safe execution."""

from __future__ import annotations

import json
import re

import structlog
from sqlalchemy import text

from app.services.llm_service import LLMService

logger = structlog.get_logger("docmind.text2sql")

DB_SCHEMA_CONTEXT = """
PostgreSQL 表结构：

documents:
  - id: VARCHAR(36)
  - tenant_id: VARCHAR(36)
  - title: VARCHAR(500)
  - file_type: VARCHAR(50)
  - status: VARCHAR(20)
  - department: VARCHAR(100)
  - access_level: INTEGER
  - chunk_count: INTEGER
  - error_message: TEXT
  - created_at: TIMESTAMP
  - updated_at: TIMESTAMP

document_chunks:
  - id: VARCHAR(36)
  - doc_id: VARCHAR(36)
  - tenant_id: VARCHAR(36)
  - content: TEXT
  - section_title: VARCHAR(500)
  - page_number: INTEGER
  - token_count: INTEGER
  - created_at: TIMESTAMP

feedback:
  - id: VARCHAR(36)
  - tenant_id: VARCHAR(36)
  - user_id: VARCHAR(36)
  - message_id: VARCHAR(36)
  - rating: INTEGER
  - correction: TEXT
  - created_at: TIMESTAMP
"""

TEXT2SQL_SYSTEM_PROMPT = f"""你是企业文档系统的 SQL 生成器。请根据用户问题生成 PostgreSQL 查询。{DB_SCHEMA_CONTEXT}

严格规则：
1. 只允许生成 SELECT 语句。
2. 必须包含 tenant_id = :tenant_id 过滤条件。
3. 不能输出解释文字，只输出 JSON。
4. JSON 格式固定为：{{"sql": "SELECT ...", "description": "查询说明"}}"""

SAFE_SQL_PATTERN = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
DANGEROUS_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE", "EXEC"}


class Text2SQLTool:
    """Generate and execute safe SQL queries from natural language."""

    def __init__(self, db_session):
        self.db = db_session

    async def generate_and_execute(self, query: str, schema_context: str = "") -> dict:
        tenant_id = self.db.info.get("tenant_id", "default")
        params = {"tenant_id": tenant_id}

        llm = LLMService()
        if not llm.is_rule_only:
            try:
                result = await llm.generate(
                    system_prompt=TEXT2SQL_SYSTEM_PROMPT,
                    user_prompt=f"用户问题：{query}",
                    temperature=0.0,
                    max_tokens=220,
                )
                if result:
                    parsed = _parse_sql_response(result)
                    if parsed and _is_safe_sql(parsed["sql"]):
                        sql = parsed["sql"]
                        logger.info("text2sql.llm_ok", sql=sql[:200], description=parsed.get("description", ""))
                        exec_result = await self._execute_safe(sql, params)
                        exec_result["description"] = parsed.get("description", "")
                        exec_result["source"] = "llm"
                        return exec_result
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                logger.warning("text2sql.llm_failed", error=str(exc))

        sql = self._heuristic_sql(query)
        if sql is None:
            return {"sql": "", "results": [], "status": "unsupported_query"}
        exec_result = await self._execute_safe(sql, params)
        exec_result["source"] = "heuristic"
        return exec_result

    async def _execute_safe(self, sql: str, params: dict) -> dict:
        try:
            if hasattr(self.db, "begin_nested"):
                async with self.db.begin_nested():
                    db_result = await self.db.execute(text(sql), params)
            else:
                db_result = await self.db.execute(text(sql), params)
            rows = self._extract_rows(db_result)
            return {"sql": sql, "results": rows, "status": "ok"}
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exec_exc:
            logger.warning("text2sql.exec_failed", sql=sql[:200], error=str(exec_exc))
            return {"sql": sql, "results": [], "status": "execution_error", "error": str(exec_exc)[:500]}

    def _extract_rows(self, db_result) -> list[dict]:
        if hasattr(db_result, "mappings"):
            mappings = db_result.mappings()
            if hasattr(mappings, "all"):
                return [dict(row) for row in mappings.all()]
            if hasattr(mappings, "first"):
                first = mappings.first()
                return [dict(first)] if first else []
        if hasattr(db_result, "all"):
            return [dict(row) for row in db_result.all()]
        if isinstance(db_result, list):
            return [dict(row) for row in db_result]
        return []

    def _heuristic_sql(self, query: str) -> str | None:
        lowered = query.lower()

        if ("文档" in query or "document" in lowered) and any(token in query or token in lowered for token in ("多少", "数量", "总数", "count", "total")):
            return "SELECT COUNT(*) AS total_documents FROM documents WHERE tenant_id = :tenant_id"
        if any(token in query or token in lowered for token in ("已完成文档", "ready documents", "处理完成", "ready")):
            return "SELECT COUNT(*) AS ready_documents FROM documents WHERE tenant_id = :tenant_id AND status = 'ready'"
        if any(token in query or token in lowered for token in ("处理中", "processing")):
            return "SELECT COUNT(*) AS processing_documents FROM documents WHERE tenant_id = :tenant_id AND status IN ('queued', 'parsing', 'chunking', 'indexing', 'retrying')"
        if any(token in query or token in lowered for token in ("失败文档", "failed")):
            return "SELECT COUNT(*) AS failed_documents FROM documents WHERE tenant_id = :tenant_id AND status = 'failed'"
        if any(token in query or token in lowered for token in ("满意度", "feedback", "评分", "平均", "rating", "average")):
            return "SELECT COALESCE(AVG(rating), 0) AS average_rating FROM feedback WHERE tenant_id = :tenant_id"
        if any(token in query or token in lowered for token in ("chunk", "分块")):
            return "SELECT COALESCE(SUM(chunk_count), 0) AS total_chunks FROM documents WHERE tenant_id = :tenant_id"
        if any(token in query or token in lowered for token in ("部门", "department")):
            return "SELECT department, COUNT(*) AS doc_count FROM documents WHERE tenant_id = :tenant_id GROUP BY department ORDER BY doc_count DESC"
        return None


def _parse_sql_response(raw: str) -> dict | None:
    text_content = raw.strip()
    try:
        data = json.loads(text_content)
        if isinstance(data, dict) and data.get("sql"):
            sql = _sanitize_sql_candidate(str(data["sql"]))
            if sql:
                return {"sql": sql, "description": str(data.get("description", ""))}
    except json.JSONDecodeError:
        pass

    code_match = re.search(r"```sql\s*(SELECT[\s\S]+?)```", text_content, re.IGNORECASE)
    if code_match:
        sql = _sanitize_sql_candidate(code_match.group(1))
        if sql:
            return {"sql": sql, "description": ""}

    select_match = re.search(r"(SELECT[^\n\r;`]+)", text_content, re.IGNORECASE)
    if select_match:
        sql = _sanitize_sql_candidate(select_match.group(1))
        if sql:
            return {"sql": sql, "description": ""}

    return None


def _sanitize_sql_candidate(sql: str) -> str | None:
    candidate = (sql or "").strip().strip("`").strip()
    candidate = candidate.split("```", 1)[0].strip()
    candidate = candidate.split("\n", 1)[0].strip()
    if "{" in candidate or "}" in candidate:
        return None
    return candidate.rstrip(";").strip() or None


def _is_safe_sql(sql: str) -> bool:
    if not sql or not SAFE_SQL_PATTERN.match(sql):
        return False
    upper = sql.upper()
    return not any(keyword in upper.split() for keyword in DANGEROUS_KEYWORDS)
