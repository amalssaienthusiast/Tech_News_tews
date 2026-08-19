"""
Google Trends Client for Dynamic Query Discovery.

Uses Google Trends to:
- Find trending tech topics in real-time
- Get related queries for topic expansion
- Monitor interest over time

Requires: pytrends library (pip install pytrends)
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TrendingTopic:
    """A trending topic from Google Trends."""
    title: str
    traffic: str  # e.g., "100K+" searches
    related_queries: List[str]
    news_url: Optional[str] = None
    
    @property
    def search_query(self) -> str:
        """Get optimized search query."""
        return f"{self.title} technology news"


@dataclass
class InterestData:
    """Interest over time data for a topic."""
    topic: str
    interest_score: int  # 0-100 relative interest
    timestamp: datetime
    is_rising: bool = False


# =============================================================================
# GOOGLE TRENDS CLIENT
# =============================================================================

class GoogleTrendsClient:
    """
    Google Trends client for trending topic discovery.
    
    Features:
    - Real-time trending searches
    - Related queries for topic expansion
    - Interest over time tracking
    - Tech-focused filtering
    """
    
    # Tech-related seed keywords for filtering
    TECH_KEYWORDS = {
        "ai", "artificial intelligence", "machine learning", "deep learning",
        "tech", "technology", "software", "hardware", "computer", "computing",
        "startup", "innovation", "digital", "cyber", "data", "cloud",
        "robot", "automation", "algorithm", "code", "programming",
        "app", "mobile", "web", "internet", "network", "security",
        "crypto", "blockchain", "bitcoin", "fintech", "saas",
        "google", "apple", "microsoft", "amazon", "meta", "nvidia",
        "openai", "chatgpt", "gpt", "llm", "semiconductor", "chip",
    }
    
    def __init__(self, geo: str = "US", hl: str = "en-US"):
        """
        Initialize Google Trends client.
        
        Args:
            geo: Geographic region (e.g., "US", "GB", "IN")
            hl: Language (e.g., "en-US", "en-GB")
        """
        self._geo = geo
        self._hl = hl
        self._pytrends_available = self._check_pytrends()
        
        if self._pytrends_available:
            logger.info(f"Google Trends client initialized (geo={geo})")
        else:
            logger.warning("pytrends not installed - install with: pip install pytrends")
    
    def _check_pytrends(self) -> bool:
        """Check if pytrends library is available."""
        try:
            from pytrends.request import TrendReq
            return True
        except ImportError:
            return False
    
    async def get_trending_searches(self) -> List[TrendingTopic]:
        """
        Get current trending searches.
        
        Returns:
            List of trending topics
        """
        if not self._pytrends_available:
            logger.warning("pytrends not available")
            return []
        
        topics = []
        
        try:
            loop = asyncio.get_running_loop()
            
            def fetch_trends():
                from pytrends.request import TrendReq
                
                pytrends = TrendReq(hl=self._hl, tz=360)
                
                # Get trending searches
                trending = pytrends.trending_searches(pn=self._geo.lower())
                return trending[0].tolist() if len(trending) > 0 else []
            
            trending_list = await loop.run_in_executor(None, fetch_trends)
            
            for title in trending_list[:20]:  # Top 20
                topics.append(TrendingTopic(
                    title=str(title),
                    traffic="",
                    related_queries=[],
                ))
            
            logger.info(f"Google Trends: {len(topics)} trending topics")
            
        except Exception as e:
            logger.warning(f"Google Trends error: {e}")
        
        return topics
    
    async def get_realtime_trending(self, category: str = "t") -> List[TrendingTopic]:
        """
        Get real-time trending topics.
        
        Args:
            category: Category filter
                - "all" = All
                - "b" = Business
                - "e" = Entertainment
                - "m" = Health
                - "t" = Sci/Tech
                - "s" = Sports
                - "h" = Top stories
        
        Returns:
            List of trending topics
        """
        if not self._pytrends_available:
            return []
        
        topics = []
        
        try:
            loop = asyncio.get_running_loop()
            
            def fetch_realtime():
                from pytrends.request import TrendReq
                
                pytrends = TrendReq(hl=self._hl, tz=360)
                
                # Real-time trending (last 24h)
                trending = pytrends.realtime_trending_searches(pn=self._geo)
                return trending
            
            df = await loop.run_in_executor(None, fetch_realtime)
            
            if df is not None and len(df) > 0:
                for _, row in df.head(30).iterrows():
                    title = row.get("entityNames", [""])[0] if "entityNames" in row else str(row.get("title", ""))
                    
                    if self._is_tech_related(title):
                        topics.append(TrendingTopic(
                            title=title,
                            traffic=str(row.get("articles", {}).get("title", "")),
                            related_queries=[],
                            news_url=row.get("articles", {}).get("url"),
                        ))
            
            logger.info(f"Google Trends realtime: {len(topics)} tech topics")
            
        except Exception as e:
            logger.debug(f"Realtime trends error: {e}")
        
        return topics
    
    async def get_related_queries(
        self,
        keyword: str,
    ) -> Dict[str, List[str]]:
        """
        Get related queries for a keyword.
        
        Args:
            keyword: Topic to find related queries for
        
        Returns:
            Dict with "top" and "rising" query lists
        """
        if not self._pytrends_available:
            return {"top": [], "rising": []}
        
        result = {"top": [], "rising": []}
        
        try:
            loop = asyncio.get_running_loop()
            
            def fetch_related():
                from pytrends.request import TrendReq
                
                pytrends = TrendReq(hl=self._hl, tz=360)
                pytrends.build_payload([keyword], timeframe="now 7-d", geo=self._geo)
                
                return pytrends.related_queries()
            
            queries = await loop.run_in_executor(None, fetch_related)
            
            if keyword in queries:
                kw_data = queries[keyword]
                
                if kw_data.get("top") is not None:
                    result["top"] = kw_data["top"]["query"].tolist()[:10]
                
                if kw_data.get("rising") is not None:
                    result["rising"] = kw_data["rising"]["query"].tolist()[:10]
            
            logger.debug(f"Related queries for '{keyword}': {len(result['top'])} top, {len(result['rising'])} rising")
            
        except Exception as e:
            logger.debug(f"Related queries error: {e}")
        
        return result
    
    async def get_tech_trending(self) -> List[str]:
        """
        Get tech-related trending search queries.
        
        Filters all trending searches for tech relevance.
        
        Returns:
            List of tech-related search queries
        """
        all_topics = await self.get_trending_searches()
        realtime = await self.get_realtime_trending(category="t")
        
        tech_queries = []
        
        # Filter for tech relevance
        for topic in all_topics + realtime:
            if self._is_tech_related(topic.title):
                tech_queries.append(topic.search_query)
        
        # Deduplicate
        seen = set()
        unique = []
        for q in tech_queries:
            q_lower = q.lower()
            if q_lower not in seen:
                seen.add(q_lower)
                unique.append(q)
        
        return unique[:15]  # Top 15 tech queries
    
    def _is_tech_related(self, text: str) -> bool:
        """Check if text is tech-related."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.TECH_KEYWORDS)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def get_trending_tech_queries(geo: str = "US") -> List[str]:
    """
    Convenience function to get trending tech queries.
    
    Args:
        geo: Geographic region
    
    Returns:
        List of trending tech search queries
    """
    client = GoogleTrendsClient(geo=geo)
    return await client.get_tech_trending()
