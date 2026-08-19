"""
Search API routes (Phase 5F).
Location: src/api/routes/search.py

Exposes full-text and substring search endpoints for canonical NormalizedArticles:
- Backed by asynchronous ArticleRepositoryProtocol
- Parameterized SQL execution via SqliteArticleRepository.search_articles()
- DTO translation via ArticleResponse.from_domain()
- Zero legacy storage dependencies
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.api.auth import verify_api_key
from src.api.routes.articles import (
    ArticleResponse,
    ArticlesListResponse,
    get_article_repository,
)
from src.storage.protocols import ArticleRepositoryProtocol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/search", tags=["Search"])


@router.get("", response_model=ArticlesListResponse)
async def search(
    q: str = Query(..., min_length=2, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    auth: dict = Depends(verify_api_key),
    repo: ArticleRepositoryProtocol = Depends(get_article_repository),
) -> ArticlesListResponse:
    """
    Search articles by title, content, summary, or tags matching query.
    """
    start = (page - 1) * per_page
    # Fetch 1 extra to deterministically calculate has_more
    raw_results = await repo.search_articles(query=q, limit=per_page + 1, offset=start)
    has_more = len(raw_results) > per_page
    page_articles = raw_results[:per_page]

    articles = [ArticleResponse.from_domain(a) for a in page_articles]

    return ArticlesListResponse(
        articles=articles,
        total=start + len(page_articles) + (1 if has_more else 0),
        page=page,
        per_page=per_page,
        has_more=has_more,
    )
