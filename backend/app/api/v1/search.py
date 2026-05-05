"""
Search API - Direct hybrid search endpoint
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.api.middleware.auth import get_current_user
from app.models.db.user import User

router = APIRouter()
_searcher = None


@router.get("/")
async def search_documents(
    q: str = Query(..., min_length=1, description="Search query"),
    top_k: int = Query(5, ge=1, le=20),
    search_type: str = Query("hybrid", pattern="^(hybrid|vector|keyword|graph)$"),
    mode: str | None = Query(None, pattern="^(hybrid|vector|keyword|graph)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Direct search endpoint (bypasses agent, useful for debugging).
    Supports: hybrid, vector-only, keyword-only, graph search.
    """
    global _searcher
    if _searcher is None:
        from app.retrieval.hybrid_searcher import HybridSearcher

        _searcher = HybridSearcher()
    effective_search_type = mode or search_type
    results = await _searcher.search(
        query=q,
        user=current_user,
        top_k=top_k,
        search_type=effective_search_type,
        db=db,
    )
    return {"query": q, "results": results, "total": len(results)}
