"""
Articles API routes (Phase 5E-E).
Location: src/api/routes/articles.py

Exposes RESTful endpoints for canonical NormalizedArticle entities:
- Backed by asynchronous ArticleRepositoryProtocol
- Canonical DTO mapping via ArticleResponse.from_domain()
- Bounded pagination and source filtering
- Resilient lookup by 16-character ID or canonical URL
- Zero direct SQLite / SQL dependencies in this layer
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth import verify_api_key
from src.domain.models import NormalizedArticle
from src.storage.protocols import ArticleRepositoryProtocol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/articles", tags=["Articles"])


# =============================================================================
# REPOSITORY DEPENDENCY INJECTION
# =============================================================================

_shared_repository: Optional[ArticleRepositoryProtocol] = None


def get_article_repository() -> ArticleRepositoryProtocol:
    """
    Get the shared ArticleRepositoryProtocol dependency.
    Raises RuntimeError if not configured via set_article_repository().
    """
    global _shared_repository
    if _shared_repository is None:
        raise RuntimeError(
            "ArticleRepository has not been initialized. "
            "Call set_article_repository(repo) during application startup."
        )
    return _shared_repository


def set_article_repository(repository: Optional[ArticleRepositoryProtocol]) -> None:
    """Inject the canonical ArticleRepositoryProtocol implementation."""
    global _shared_repository
    _shared_repository = repository


# =============================================================================
# CANONICAL DTO RESPONSE MODELS
# =============================================================================

class ArticleResponse(BaseModel):
    """Canonical Single Article DTO."""
    id: str
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    sentiment_score: Optional[float] = None
    topics: List[str] = []

    @classmethod
    def from_domain(cls, article: NormalizedArticle) -> ArticleResponse:
        """Construct canonical API DTO from NormalizedArticle domain entity."""
        sentiment: Optional[float] = None
        if isinstance(article.metadata, dict):
            raw_sentiment = article.metadata.get("sentiment_score")
            if isinstance(raw_sentiment, (int, float)):
                sentiment = float(raw_sentiment)

        # Summary fallback: prefer summary, fallback to clean_text snippet
        summary_text = article.summary
        if not summary_text and article.clean_text:
            summary_text = article.clean_text[:300].strip()

        return cls(
            id=article.id,
            title=article.title,
            url=article.canonical_url,
            source=article.source_name or article.source_id,
            published_at=article.published_at.isoformat() if article.published_at else None,
            summary=summary_text or None,
            sentiment_score=sentiment,
            topics=list(article.tags or ()),
        )


class ArticlesListResponse(BaseModel):
    """Canonical Paginated List of Articles DTO."""
    articles: List[ArticleResponse]
    total: int
    page: int
    per_page: int
    has_more: bool


class ArticleSearchResultResponse(BaseModel):
    """Canonical Full-Text Search Single Result DTO."""
    article: ArticleResponse
    relevance_score: float
    snippet: str


class ArticleSearchListResponse(BaseModel):
    """Canonical Paginated Full-Text Search Response DTO."""
    results: List[ArticleSearchResultResponse]
    query: str
    page: int
    per_page: int
    count: int


# =============================================================================
# REST ENDPOINTS
# =============================================================================

@router.get("/search", response_model=ArticleSearchListResponse)
async def search_articles(
    q: str = Query(..., min_length=1, max_length=200, description="Search query string"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    source: Optional[str] = Query(None, description="Filter by source ID"),
    tag: Optional[str] = Query(None, description="Filter by topic tag"),
    auth: dict = Depends(verify_api_key),
    repo: ArticleRepositoryProtocol = Depends(get_article_repository),
) -> ArticleSearchListResponse:
    """
    Ranked full-text search against canonical articles using SQLite FTS5 BM25.
    """
    offset = (page - 1) * per_page
    search_results = await repo.search_articles_fts(
        query=q,
        limit=per_page,
        offset=offset,
        source_id=source.strip() if source else None,
        tag=tag.strip() if tag else None,
    )

    items = [
        ArticleSearchResultResponse(
            article=ArticleResponse.from_domain(r.article),
            relevance_score=float(r.relevance_score),
            snippet=r.snippet,
        )
        for r in search_results
    ]

    return ArticleSearchListResponse(
        results=items,
        query=q,
        page=page,
        per_page=per_page,
        count=len(items),
    )


@router.get("", response_model=ArticlesListResponse)
async def list_articles(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    source: Optional[str] = Query(None, description="Filter by source ID"),
    auth: dict = Depends(verify_api_key),
    repo: ArticleRepositoryProtocol = Depends(get_article_repository),
) -> ArticlesListResponse:
    """
    Get paginated list of canonical articles ordered by discovered_at DESC.
    """
    offset = (page - 1) * per_page
    articles = await repo.get_recent_articles(
        limit=per_page,
        offset=offset,
        source_id=source.strip() if source else None,
    )
    total = await repo.count_articles()

    items = [ArticleResponse.from_domain(a) for a in articles]
    has_more = (offset + len(items)) < total

    return ArticlesListResponse(
        articles=items,
        total=total,
        page=page,
        per_page=per_page,
        has_more=has_more,
    )


@router.get("/{article_id:path}", response_model=ArticleResponse)
async def get_article(
    article_id: str,
    auth: dict = Depends(verify_api_key),
    repo: ArticleRepositoryProtocol = Depends(get_article_repository),
) -> ArticleResponse:
    """
    Get a single canonical article by its 16-character ID or canonical URL.
    """
    cleaned_id = article_id.strip()

    # 1. Primary lookup by hash ID
    article = await repo.get_article(cleaned_id)

    # 2. Secondary fallback lookup by canonical URL
    if article is None:
        article = await repo.get_article_by_canonical_url(cleaned_id)

    if article is None:
        raise HTTPException(
            status_code=404,
            detail=f"Article '{cleaned_id}' not found",
        )

    return ArticleResponse.from_domain(article)
