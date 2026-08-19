"""
Personalization Engine - Content-based recommendations using UserPreferences.

Connects the existing UserPreferences system to article scoring and filtering,
enabling personalized news feeds based on user topics, watchlists, and interests.

Usage:
    from src.personalization import PersonalizationEngine
    
    engine = PersonalizationEngine(user_prefs)
    scored = engine.score_articles(articles)
    filtered = engine.filter_by_preferences(articles)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Set, Tuple

# Import UserPreferences if available
try:
    from src.user.preferences import UserPreferences
    HAS_PREFERENCES = True
except ImportError:
    HAS_PREFERENCES = False
    UserPreferences = None

logger = logging.getLogger(__name__)


@dataclass
class ScoredArticle:
    """Article with personalization score."""
    article: Dict[str, Any]
    relevance_score: float = 0.0
    topic_matches: List[str] = field(default_factory=list)
    company_matches: List[str] = field(default_factory=list)
    source_boost: float = 0.0
    recency_boost: float = 0.0
    total_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = dict(self.article)
        result["personalization"] = {
            "relevance_score": self.relevance_score,
            "topic_matches": self.topic_matches,
            "company_matches": self.company_matches,
            "source_boost": self.source_boost,
            "total_score": self.total_score,
        }
        return result


class PersonalizationEngine:
    """
    Personalization engine for content-based article recommendations.
    
    Features:
    - Topic interest matching
    - Company watchlist matching
    - Source preference weighting
    - Recency scoring
    - Combined relevance scoring
    """
    
    # Scoring weights
    TOPIC_WEIGHT = 0.4
    COMPANY_WEIGHT = 0.3
    SOURCE_WEIGHT = 0.15
    RECENCY_WEIGHT = 0.15
    
    def __init__(
        self,
        preferences: Optional["UserPreferences"] = None,
    ) -> None:
        """
        Initialize personalization engine.
        
        Args:
            preferences: User preferences object
        """
        self.preferences = preferences
        
        # Build lookup sets for fast matching
        self._topic_keywords: Dict[str, Set[str]] = {}
        self._companies: Set[str] = set()
        self._preferred_sources: Dict[str, float] = {}
        
        if preferences:
            self._build_lookups()
    
    def _build_lookups(self) -> None:
        """Build lookup structures from preferences."""
        if not self.preferences:
            return
        
        # Topic keywords for matching
        for topic in self.preferences.topics:
            name = topic.name.lower()
            keywords = {name}
            keywords.update(kw.lower() for kw in topic.keywords)
            self._topic_keywords[name] = keywords
        
        # Company names and tickers
        for company in self.preferences.watchlist_companies:
            self._companies.add(company.name.lower())
            self._companies.add(company.ticker.lower())
            # Add common variations
            self._companies.add(company.name.lower().replace(" ", ""))
        
        # Source preferences
        for source in self.preferences.preferred_sources:
            self._preferred_sources[source.domain.lower()] = source.weight
    
    def update_preferences(self, preferences: "UserPreferences") -> None:
        """Update preferences and rebuild lookups."""
        self.preferences = preferences
        self._topic_keywords.clear()
        self._companies.clear()
        self._preferred_sources.clear()
        self._build_lookups()
    
    def score_article(self, article: Dict[str, Any]) -> ScoredArticle:
        """
        Calculate personalization score for a single article.
        
        Args:
            article: Article dictionary
        
        Returns:
            ScoredArticle with scores and matches
        """
        scored = ScoredArticle(article=article)
        
        if not self.preferences:
            return scored
        
        # Get article text for matching
        title = article.get("title", "").lower()
        summary = article.get("ai_summary", "").lower()
        content = article.get("full_content", "").lower()
        source = article.get("source", "").lower()
        
        text = f"{title} {summary} {content}"
        
        # Topic matching
        topic_score = 0.0
        for topic_name, keywords in self._topic_keywords.items():
            matches = sum(1 for kw in keywords if kw in text)
            if matches > 0:
                scored.topic_matches.append(topic_name)
                # Weight by number of keyword matches
                topic_score += min(matches * 0.2, 1.0)
        
        if self._topic_keywords:
            topic_score = min(topic_score, 1.0)
        scored.relevance_score = topic_score
        
        # Company matching
        company_score = 0.0
        for company in self._companies:
            if company in text:
                scored.company_matches.append(company)
                company_score += 0.5
        
        company_score = min(company_score, 1.0)
        
        # Source preference
        source_score = 0.0
        for domain, weight in self._preferred_sources.items():
            if domain in source:
                source_score = weight
                break
        
        scored.source_boost = source_score
        
        # Recency (articles within 24h get boost)
        recency_score = 0.0
        published = article.get("published")
        if published:
            try:
                if isinstance(published, str):
                    from dateutil import parser
                    pub_date = parser.isoparse(published)
                else:
                    pub_date = published
                
                age_hours = (datetime.now(UTC) - pub_date).total_seconds() / 3600
                if age_hours < 1:
                    recency_score = 1.0
                elif age_hours < 6:
                    recency_score = 0.8
                elif age_hours < 24:
                    recency_score = 0.5
                else:
                    recency_score = max(0, 1 - (age_hours / 72))
            except Exception as e:
                logger.debug(f"score_article: suppressed {type(e).__name__}: {e}")
        
        scored.recency_boost = recency_score
        
        # Calculate total score
        scored.total_score = (
            self.TOPIC_WEIGHT * topic_score +
            self.COMPANY_WEIGHT * company_score +
            self.SOURCE_WEIGHT * source_score +
            self.RECENCY_WEIGHT * recency_score
        )
        
        return scored
    
    def score_articles(
        self,
        articles: List[Dict[str, Any]],
        min_score: float = 0.0,
    ) -> List[ScoredArticle]:
        """
        Score and sort articles by personalization relevance.
        
        Args:
            articles: List of article dictionaries
            min_score: Minimum score threshold
        
        Returns:
            Sorted list of ScoredArticle objects
        """
        scored = [self.score_article(a) for a in articles]
        
        # Filter by minimum score
        if min_score > 0:
            scored = [s for s in scored if s.total_score >= min_score]
        
        # Sort by total score descending
        scored.sort(key=lambda x: x.total_score, reverse=True)
        
        return scored
    
    def filter_by_preferences(
        self,
        articles: List[Dict[str, Any]],
        require_topic: bool = False,
        require_company: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Filter articles based on user preferences.
        
        Args:
            articles: List of article dictionaries
            require_topic: Only include articles matching topics
            require_company: Only include articles matching companies
        
        Returns:
            Filtered article list
        """
        if not self.preferences:
            return articles
        
        scored = self.score_articles(articles)
        
        filtered = []
        for s in scored:
            if require_topic and not s.topic_matches:
                continue
            if require_company and not s.company_matches:
                continue
            filtered.append(s.to_dict())
        
        return filtered
    
    def get_top_articles(
        self,
        articles: List[Dict[str, Any]],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get top personalized articles.
        
        Args:
            articles: List of article dictionaries
            limit: Maximum articles to return
        
        Returns:
            Top scored articles
        """
        scored = self.score_articles(articles)
        return [s.to_dict() for s in scored[:limit]]
    
    def explain_score(self, article: Dict[str, Any]) -> str:
        """
        Generate explanation for article's personalization score.
        
        Args:
            article: Article dictionary
        
        Returns:
            Human-readable explanation
        """
        scored = self.score_article(article)
        
        parts = []
        parts.append(f"Total Score: {scored.total_score:.2f}")
        
        if scored.topic_matches:
            parts.append(f"Topics: {', '.join(scored.topic_matches)}")
        
        if scored.company_matches:
            parts.append(f"Companies: {', '.join(scored.company_matches)}")
        
        if scored.source_boost > 0:
            parts.append(f"Source boost: +{scored.source_boost:.2f}")
        
        if scored.recency_boost > 0:
            parts.append(f"Recency: +{scored.recency_boost:.2f}")
        
        return " | ".join(parts)


# Singleton for global access
_engine: Optional[PersonalizationEngine] = None


def get_personalization_engine(
    preferences: Optional["UserPreferences"] = None,
) -> PersonalizationEngine:
    """Get or create singleton PersonalizationEngine."""
    global _engine
    
    if _engine is None:
        _engine = PersonalizationEngine(preferences=preferences)
    elif preferences:
        _engine.update_preferences(preferences)
    
    return _engine
