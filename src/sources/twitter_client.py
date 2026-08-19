"""
Twitter/X API Client for Tech News Discovery.

Uses Tweepy library for Twitter API v2 access with bearer token authentication.
Provides app-only read access to search recent tweets for tech news.

Rate Limits (App-only):
- Recent search: 450 requests / 15 min
- Full archive search: 300 requests / 15 min (Academic tier)
"""

import os
import logging
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Check for tweepy
try:
    import tweepy
    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False
    logger.warning("Tweepy not installed. Twitter integration disabled. Install with: pip install tweepy>=4.14.0")


@dataclass
class Tweet:
    """Represents a tweet with relevant metadata."""
    id: str
    text: str
    author_id: str
    author_username: str
    created_at: datetime
    url: str
    retweet_count: int = 0
    like_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    source: str = "twitter"
    
    # Optional enriched fields
    author_name: Optional[str] = None
    author_verified: bool = False
    media_urls: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    mentions: List[str] = field(default_factory=list)
    
    @property
    def engagement_score(self) -> float:
        """Calculate engagement score based on metrics."""
        return (
            self.retweet_count * 2.0 +
            self.like_count * 1.0 +
            self.reply_count * 1.5 +
            self.quote_count * 2.5
        )
    
    def to_unified_article(self) -> Dict[str, Any]:
        """Convert to unified article format for aggregator."""
        return {
            "title": self._extract_title(),
            "url": self.url,
            "source": f"Twitter/@{self.author_username}",
            "published_at": self.created_at,
            "summary": self.text,
            "content": self.text,
            "author": self.author_name or self.author_username,
            "keywords": self.hashtags,
            "metadata": {
                "tweet_id": self.id,
                "engagement_score": self.engagement_score,
                "retweets": self.retweet_count,
                "likes": self.like_count,
                "verified": self.author_verified,
            }
        }
    
    def _extract_title(self) -> str:
        """Extract a title from tweet text (first sentence or first 100 chars)."""
        text = self.text.strip()
        # Remove URLs for title
        import re
        text = re.sub(r'https?://\S+', '', text).strip()
        
        # First sentence
        for sep in ['. ', '! ', '? ', '\n']:
            if sep in text:
                return text.split(sep)[0] + sep.strip()
        
        # Truncate if too long
        if len(text) > 100:
            return text[:97] + "..."
        return text


class TwitterClient:
    """
    Twitter/X API v2 client for tech news discovery.
    
    Uses bearer token for app-only authentication (read-only access).
    Searches recent tweets (last 7 days) for tech-related content.
    """
    
    # Default tech-related search queries
    DEFAULT_QUERIES = [
        "(tech OR technology) (news OR announcement) -is:retweet lang:en",
        "(AI OR artificial intelligence) (breakthrough OR launch) -is:retweet lang:en",
        "(startup OR funding OR Series) (tech OR AI) -is:retweet lang:en",
        "(Apple OR Google OR Microsoft OR Meta OR Amazon) (announces OR launches) -is:retweet lang:en",
        "(cybersecurity OR data breach OR hacking) -is:retweet lang:en",
    ]
    
    # High-quality tech accounts to prioritize
    PRIORITY_ACCOUNTS = [
        "TechCrunch", "TheVerge", "Wired", "engadget", "ArsTechnica",
        "mashable", "techreview", "ZDNET", "Gaborit", "VentureBeat",
        "caborit", "reuters", "BBCTech", "CNBCtech", "ForbesTech",
    ]
    
    def __init__(
        self,
        bearer_token: Optional[str] = None,
        max_results_per_query: int = 20,
        cache_ttl_seconds: int = 300,
    ):
        """
        Initialize Twitter client.
        
        Args:
            bearer_token: Twitter API v2 bearer token. Falls back to TWITTER_BEARER_TOKEN env var.
            max_results_per_query: Max tweets per search query (10-100).
            cache_ttl_seconds: Cache duration for results.
        """
        self.bearer_token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN")
        self.max_results = min(max(max_results_per_query, 10), 100)
        self.cache_ttl = cache_ttl_seconds
        
        self._client: Optional["tweepy.Client"] = None
        self._cache: Dict[str, tuple] = {}  # query -> (timestamp, results)
        self._initialized = False
        
        if not TWEEPY_AVAILABLE:
            logger.error("Tweepy not available. Twitter client disabled.")
            return
        
        if not self.bearer_token:
            logger.warning("TWITTER_BEARER_TOKEN not set. Twitter client will be disabled.")
            return
        
        self._initialize_client()
    
    def _initialize_client(self) -> bool:
        """Initialize the Tweepy client."""
        if not TWEEPY_AVAILABLE or not self.bearer_token:
            return False
        
        try:
            self._client = tweepy.Client(
                bearer_token=self.bearer_token,
                wait_on_rate_limit=True,
            )
            self._initialized = True
            logger.info("Twitter client initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Twitter client: {e}")
            return False
    
    @property
    def is_available(self) -> bool:
        """Check if the client is properly configured and available."""
        return self._initialized and self._client is not None
    
    async def search_tech_news(
        self,
        custom_queries: Optional[List[str]] = None,
        max_age_hours: int = 24,
    ) -> List[Tweet]:
        """
        Search for recent tech news tweets.
        
        Args:
            custom_queries: Optional custom search queries. Uses defaults if not provided.
            max_age_hours: Maximum age of tweets to include.
            
        Returns:
            List of Tweet objects sorted by engagement.
        """
        if not self.is_available:
            logger.debug("Twitter client not available, returning empty results")
            return []
        
        queries = custom_queries or self.DEFAULT_QUERIES
        all_tweets: List[Tweet] = []
        
        # Calculate time threshold
        start_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        for query in queries:
            # Check cache
            cache_key = f"{query}:{max_age_hours}"
            if cache_key in self._cache:
                cached_time, cached_results = self._cache[cache_key]
                if (datetime.utcnow() - cached_time).total_seconds() < self.cache_ttl:
                    all_tweets.extend(cached_results)
                    continue
            
            try:
                tweets = await self._execute_search(query, start_time)
                self._cache[cache_key] = (datetime.utcnow(), tweets)
                all_tweets.extend(tweets)
            except Exception as e:
                logger.warning(f"Twitter search failed for query '{query[:30]}...': {e}")
        
        # Deduplicate by tweet ID
        seen_ids = set()
        unique_tweets = []
        for tweet in all_tweets:
            if tweet.id not in seen_ids:
                seen_ids.add(tweet.id)
                unique_tweets.append(tweet)
        
        # Sort by engagement
        unique_tweets.sort(key=lambda t: t.engagement_score, reverse=True)
        
        logger.info(f"Twitter: Found {len(unique_tweets)} unique tech tweets")
        return unique_tweets
    
    async def _execute_search(
        self,
        query: str,
        start_time: datetime,
    ) -> List[Tweet]:
        """Execute a single search query."""
        if not self._client:
            return []
        
        # Run in executor since tweepy is synchronous
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.search_recent_tweets(
                query=query,
                max_results=self.max_results,
                start_time=start_time.isoformat() + "Z",
                tweet_fields=["created_at", "public_metrics", "author_id", "source", "entities"],
                user_fields=["username", "name", "verified"],
                expansions=["author_id", "attachments.media_keys"],
                media_fields=["url", "preview_image_url"],
            )
        )
        
        if not response or not response.data:
            return []
        
        # Build user lookup
        users = {}
        if response.includes and "users" in response.includes:
            for user in response.includes["users"]:
                users[user.id] = user
        
        # Convert to Tweet objects
        tweets = []
        for tweet_data in response.data:
            user = users.get(tweet_data.author_id)
            
            # Extract hashtags
            hashtags = []
            mentions = []
            if tweet_data.entities:
                if "hashtags" in tweet_data.entities:
                    hashtags = [h["tag"] for h in tweet_data.entities["hashtags"]]
                if "mentions" in tweet_data.entities:
                    mentions = [m["username"] for m in tweet_data.entities["mentions"]]
            
            # Get metrics
            metrics = tweet_data.public_metrics or {}
            
            tweet = Tweet(
                id=str(tweet_data.id),
                text=tweet_data.text,
                author_id=str(tweet_data.author_id),
                author_username=user.username if user else "unknown",
                author_name=user.name if user else None,
                author_verified=getattr(user, "verified", False) if user else False,
                created_at=tweet_data.created_at,
                url=f"https://twitter.com/{user.username if user else 'i'}/status/{tweet_data.id}",
                retweet_count=metrics.get("retweet_count", 0),
                like_count=metrics.get("like_count", 0),
                reply_count=metrics.get("reply_count", 0),
                quote_count=metrics.get("quote_count", 0),
                hashtags=hashtags,
                mentions=mentions,
            )
            tweets.append(tweet)
        
        return tweets
    
    async def get_user_timeline(
        self,
        username: str,
        max_results: int = 10,
    ) -> List[Tweet]:
        """
        Get recent tweets from a specific user.
        
        Args:
            username: Twitter username (without @).
            max_results: Maximum tweets to fetch.
            
        Returns:
            List of Tweet objects.
        """
        if not self.is_available:
            return []
        
        try:
            loop = asyncio.get_running_loop()
            
            # First get user ID
            user_response = await loop.run_in_executor(
                None,
                lambda: self._client.get_user(username=username, user_fields=["id", "name", "verified"])
            )
            
            if not user_response or not user_response.data:
                logger.warning(f"User @{username} not found")
                return []
            
            user = user_response.data
            
            # Get timeline
            timeline_response = await loop.run_in_executor(
                None,
                lambda: self._client.get_users_tweets(
                    id=user.id,
                    max_results=max_results,
                    tweet_fields=["created_at", "public_metrics", "entities"],
                    exclude=["retweets", "replies"],
                )
            )
            
            if not timeline_response or not timeline_response.data:
                return []
            
            tweets = []
            for tweet_data in timeline_response.data:
                metrics = tweet_data.public_metrics or {}
                hashtags = []
                if tweet_data.entities and "hashtags" in tweet_data.entities:
                    hashtags = [h["tag"] for h in tweet_data.entities["hashtags"]]
                
                tweet = Tweet(
                    id=str(tweet_data.id),
                    text=tweet_data.text,
                    author_id=str(user.id),
                    author_username=username,
                    author_name=user.name,
                    author_verified=getattr(user, "verified", False),
                    created_at=tweet_data.created_at,
                    url=f"https://twitter.com/{username}/status/{tweet_data.id}",
                    retweet_count=metrics.get("retweet_count", 0),
                    like_count=metrics.get("like_count", 0),
                    reply_count=metrics.get("reply_count", 0),
                    quote_count=metrics.get("quote_count", 0),
                    hashtags=hashtags,
                )
                tweets.append(tweet)
            
            return tweets
            
        except Exception as e:
            logger.error(f"Failed to fetch timeline for @{username}: {e}")
            return []
    
    async def fetch_priority_accounts(self, tweets_per_account: int = 5) -> List[Tweet]:
        """
        Fetch recent tweets from priority tech news accounts.
        
        Args:
            tweets_per_account: Number of tweets to fetch per account.
            
        Returns:
            List of Tweet objects from priority accounts.
        """
        if not self.is_available:
            return []
        
        all_tweets = []
        for account in self.PRIORITY_ACCOUNTS[:10]:  # Limit to avoid rate limits
            try:
                tweets = await self.get_user_timeline(account, tweets_per_account)
                all_tweets.extend(tweets)
            except Exception as e:
                logger.debug(f"Could not fetch @{account}: {e}")
        
        return all_tweets


# Convenience function for quick usage
async def fetch_tech_tweets(
    bearer_token: Optional[str] = None,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """
    Convenience function to fetch tech tweets as unified articles.
    
    Args:
        bearer_token: Optional bearer token (uses env var if not provided).
        max_results: Maximum total tweets to return.
        
    Returns:
        List of article dictionaries ready for aggregator.
    """
    client = TwitterClient(bearer_token=bearer_token)
    if not client.is_available:
        return []
    
    tweets = await client.search_tech_news()
    
    # Convert to unified format and limit
    articles = [tweet.to_unified_article() for tweet in tweets[:max_results]]
    return articles
