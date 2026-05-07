"""Generation prompts for answer synthesis."""

# TODO: [AI_API] Used by Generator Node

GENERATION_PROMPT = """请基于以下检索到的文档回答用户问题。

规则：
1. 只能使用提供的文档内容作答。
2. 每条事实性结论都要标注引用，例如：[来源：文档标题，第 X 页]。
3. 如果证据不足，请明确说明“根据现有文档，暂时无法完整回答该问题”。
4. 回答结构为：先给结论，再分点展开。
5. 回答风格遵循用户偏好：{answer_style}

文档证据：
{context}

用户问题：{query}

回答："""

TEXT2SQL_PROMPT = """Given the following database schema, generate a PostgreSQL query.

Schema:
{schema}

Question: {query}

Rules:
- Generate ONLY a SELECT query (no INSERT, UPDATE, DELETE, DROP)
- Use appropriate aggregation functions
- Return well-formatted results

SQL:"""
