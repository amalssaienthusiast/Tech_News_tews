"""
News Sources Module.

Provides API clients for multiple news discovery sources:
- Google News (RSS + Custom Search API)
- Bing News (Azure Cognitive Services)
- NewsAPI.org
- DuckDuckGo (no API key required)
- Reddit (public JSON API)
- Google Trends (trending topics)
- Discovery Aggregator (unified interface)
"""

from src.sources.google_news import GoogleNewsClient, GoogleNewsRSS, NewsArticle
from src.sources.bing_news import BingNewsClient, BingNewsArticle
from src.sources.newsapi_client import NewsAPIClient, NewsAPIArticle
from src.sources.aggregator import DiscoveryAggregator, UnifiedArticle

# New sources
from src.sources.duckduckgo_search import DuckDuckGoClient, DuckDuckGoArticle
from src.sources.reddit_client import RedditClient, RedditPost
from src.sources.google_trends import GoogleTrendsClient, TrendingTopic

# Twitter (requires bearer token)
try:
    from src.sources.twitter_client import TwitterClient, Tweet
    TWITTER_AVAILABLE = True
except ImportError:
    TWITTER_AVAILABLE = False

__all__ = [
    # Original sources
    "GoogleNewsClient",
    "GoogleNewsRSS",
    "NewsArticle",
    "BingNewsClient",
    "BingNewsArticle",
    "NewsAPIClient",
    "NewsAPIArticle",
    "DiscoveryAggregator",
    "UnifiedArticle",
    # New sources
    "DuckDuckGoClient",
    "DuckDuckGoArticle",
    "RedditClient",
    "RedditPost",
    "GoogleTrendsClient",
    "TrendingTopic",
    # Twitter
    "TwitterClient",
    "Tweet",
    "TWITTER_AVAILABLE",
]

