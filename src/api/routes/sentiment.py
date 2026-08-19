"""
Sentiment API routes (Phase 5F).
Location: src/api/routes/sentiment.py

Exposes sentiment analysis and trend discovery endpoints:
- On-demand analysis using SentimentAnalyzer
- Stored sentiment retrieval via ArticleRepositoryProtocol
- Zero legacy storage dependencies
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth import verify_api_key
from src.api.schemas import SentimentResponse, TrendResponse
from src.api.routes.articles import get_article_repository
from src.storage.protocols import ArticleRepositoryProtocol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sentiment", tags=["Sentiment"])


@router.get("/analyze", response_model=SentimentResponse)
async def analyze_text(
    text: str = Query(..., min_length=10, description="Text to analyze"),
    auth: dict = Depends(verify_api_key),
) -> SentimentResponse:
    """Analyze sentiment of provided text."""
    from src.intelligence.sentiment_analyzer import get_sentiment_analyzer

    analyzer = get_sentiment_analyzer()
    result = analyzer.analyze(text, persist=False)

    return SentimentResponse(
        score=result.score,
        label=result.label.value,
        emoji=result.label.emoji,
        topics=result.topics,
        keywords=result.keywords_detected,
    )


@router.get("/trends", response_model=List[TrendResponse])
async def get_trends(
    period: str = Query("24h", pattern="^(24h|7d|30d)$"),
    auth: dict = Depends(verify_api_key),
) -> List[TrendResponse]:
    """Get sentiment trends across topics."""
    from src.intelligence.sentiment_analyzer import get_sentiment_analyzer

    analyzer = get_sentiment_analyzer()
    summary = analyzer.get_topic_sentiment_summary()

    trends = []
    for topic, trend in summary.items():
        trends.append(
            TrendResponse(
                topic=topic,
                period=period,
                avg_score=trend.avg_score,
                score_change=trend.score_change,
                article_count=trend.article_count,
                trend_direction=trend.trend_direction,
            )
        )

    return trends


@router.get("/article/{article_id:path}", response_model=SentimentResponse)
async def get_article_sentiment(
    article_id: str,
    auth: dict = Depends(verify_api_key),
    repo: ArticleRepositoryProtocol = Depends(get_article_repository),
) -> SentimentResponse:
    """Get stored sentiment for an article by ID or canonical URL."""
    from src.intelligence.sentiment_analyzer import get_sentiment_analyzer

    analyzer = get_sentiment_analyzer()
    clean_id = article_id.strip()
    result = analyzer.get_sentiment(clean_id)

    if not result:
        # Resolve article from canonical article repository
        article = await repo.get_article(clean_id)
        if not article:
            article = await repo.get_article_by_canonical_url(clean_id)

        if article:
            text = article.clean_text or article.title
            result = analyzer.analyze(text, article_id=article.id)

    if not result:
        raise HTTPException(status_code=404, detail="Article not found")

    return SentimentResponse(
        score=result.score,
        label=result.label.value,
        emoji=result.label.emoji,
        topics=result.topics,
        keywords=result.keywords_detected,
    )
