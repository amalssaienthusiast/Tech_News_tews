"""
Pydantic API Schemas for Tech News Scraper.
Location: src/api/schemas.py
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ArticleResponse(BaseModel):
    """Single article response schema."""
    id: str
    title: str
    url: str
    source: str
    category: Optional[str] = None
    summary: Optional[str] = None
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    published_at: Optional[str] = None
    discovered_at: Optional[str] = None
    image_url: Optional[str] = None
    entities: List[str] = []
    topics: List[str] = []


class ArticlesListResponse(BaseModel):
    """Paginated articles response."""
    articles: List[ArticleResponse]
    total: int
    page: int
    per_page: int
    has_more: bool


class SentimentResponse(BaseModel):
    """Sentiment analysis response schema."""
    score: float = Field(description="Sentiment score from -1.0 to 1.0")
    label: str = Field(description="Sentiment label (positive/negative/neutral)")
    emoji: str = ""
    topics: Dict[str, float] = {}
    keywords: List[str] = []


class TrendResponse(BaseModel):
    """Sentiment trend response schema."""
    topic: str
    period: str
    avg_score: float
    score_change: float
    article_count: int
    trend_direction: str


class HealthResponse(BaseModel):
    """Health check response schema."""
    status: str
    version: str
    timestamp: str
    database: str
    articles_count: int
    events_count: Optional[int] = 0
