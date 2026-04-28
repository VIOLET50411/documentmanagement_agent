"""Routing prompts for intent classification."""

# TODO: [AI_API] Used by Intent Router Node

INTENT_CLASSIFICATION_PROMPT = """Classify the following user query into one category:
- qa: Factual questions about company policies/documents
- statistics: Data analysis, calculations, comparisons with numbers
- summarize: Requests to summarize or extract key points from documents
- graph: Questions about relationships between entities across documents
- tool_call: Requests to check real-time data (leave balance, expense status)

User query: {query}
User profile: {user_profile}

Category:"""

QUERY_REWRITE_PROMPT = """Given the conversation history and user query, rewrite the query to be self-contained.
Replace pronouns and references with specific names/documents.

Conversation history:
{history}

Current query: {query}

Rewritten query:"""
