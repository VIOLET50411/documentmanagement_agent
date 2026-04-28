"""Generation prompts for answer synthesis."""

# TODO: [AI_API] Used by Generator Node

GENERATION_PROMPT = """Based on the following retrieved documents, answer the user's question.

RULES:
1. Use ONLY information from the provided documents
2. Cite every factual claim: [Source: Document Title — Page X]
3. If documents are insufficient, say "根据现有文档，无法完全回答此问题"
4. Structure your answer: conclusion first, then bullet-pointed details
5. Use the user's preferred answer style: {answer_style}

Documents:
{context}

Question: {query}

Answer:"""

TEXT2SQL_PROMPT = """Given the following database schema, generate a PostgreSQL query.

Schema:
{schema}

Question: {query}

Rules:
- Generate ONLY a SELECT query (no INSERT, UPDATE, DELETE, DROP)
- Use appropriate aggregation functions
- Return well-formatted results

SQL:"""
