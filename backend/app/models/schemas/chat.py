"""Pydantic schemas for Chat API."""
from pydantic import BaseModel
from typing import Optional, List


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    search_type: str = "hybrid"  # hybrid, vector, keyword, graph


class Citation(BaseModel):
    doc_id: str
    doc_title: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    snippet: str
    relevance_score: float


class ChatResponse(BaseModel):
    message_id: str
    answer: str
    citations: List[Citation] = []
    agent_used: Optional[str] = None
    cached: bool = False
    thread_id: Optional[str] = None
