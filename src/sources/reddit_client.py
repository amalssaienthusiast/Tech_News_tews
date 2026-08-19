"""
Reddit API Client for Tech News Discovery.

Fetches trending posts from tech-related subreddits:
- r/technology
- r/programming
- r/machinelearning
- r/artificial
- r/startups

Supports both authenticated (PRAW) and unauthenticated (JSON API) access.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import List, Optional
from urllib.parse import urljoin

import aiohttp

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

try:
    from config.settings import (
        REDDIT_CLIENT_ID,
        REDDIT_CLIENT_SECRET,
        REDDIT_USER_AGENT,
    )
except ImportError:
    REDDIT_CLIENT_ID = ""
    REDDIT_CLIENT_SECRET = ""
    REDDIT_USER_AGENT = "TechNewsScraper/1.0"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class RedditPost:
    """Reddit post containing tech news."""
    id: str
    url: str
    title: str
    subreddit: str
    author: str
    score: int
    num_comments: int
    created_utc: datetime
    selftext: str = ""
    link_url: str = ""  # External link if link post
    is_self: bool = True
    
    @property
    def external_url(self) -> str:
        """Get external URL if link post, otherwise Reddit URL."""
        return self.link_url if self.link_url and not self.is_self else self.url
    
    @classmethod
    def from_json(cls, data: dict, subreddit: str) -> "RedditPost":
        """Create from Reddit JSON API response."""
        post_data = data.get("data", data)
        
        post_id = post_data.get("id", "")
        permalink = post_data.get("permalink", f"/r/{subreddit}/comments/{post_id}")
        
        return cls(
            id=post_id,
            url=f"https://reddit.com{permalink}",
            title=post_data.get("title", ""),
            subreddit=post_data.get("subreddit", subreddit),
            author=post_data.get("author", "[deleted]"),
            score=post_data.get("score", 0),
            num_comments=post_data.get("num_comments", 0),
            created_utc=datetime.fromtimestamp(
                post_data.get("created_utc", 0), 
                tz=UTC
            ),
            selftext=post_data.get("selftext", "")[:500],  # Limit text
            link_url=post_data.get("url", ""),
            is_self=post_data.get("is_self", True),
        )


# =============================================================================
# REDDIT CLIENT
# =============================================================================

class RedditClient:
    """
    Reddit client for tech news discovery.
    
    Features:
    - Fetches from multiple tech subreddits
    - Supports hot/new/rising sorting
    - Works without API key (JSON endpoint)
    - Optional PRAW for authenticated access
    """
    
    # Tech-focused subreddits
    DEFAULT_SUBREDDITS = [
        "technology",
        "programming", 
        "machinelearning",
        "artificial",
        "startups",
        "technews",
        "coding",
        "webdev",
    ]
    
    BASE_URL = "https://www.reddit.com"
    
    def __init__(
        self,
        client_id: str = REDDIT_CLIENT_ID,
        client_secret: str = REDDIT_CLIENT_SECRET,
        user_agent: str = REDDIT_USER_AGENT,
        subreddits: Optional[List[str]] = None,
    ):
        """
        Initialize Reddit client.
        
        Args:
            client_id: Reddit API client ID
            client_secret: Reddit API client secret
            user_agent: User agent for requests
            subreddits: Subreddits to monitor
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._subreddits = subreddits or self.DEFAULT_SUBREDDITS
        self._praw_available = self._check_praw()
        self._auth_disabled_logged = False  # dedup the "no auth" warning

        if self._client_id and self._client_secret:
            logger.info("Reddit client initialized with API credentials")
        else:
            # Reddit tightened their public JSON API in mid-2024 — unauthenticated
            # requests now 403 across the board. Log ONE actionable warning at
            # init, then skip requests silently to avoid spamming 403 logs.
            logger.warning(
                "Reddit client initialized WITHOUT API credentials. "
                "Reddit's public JSON API now 403s unauthenticated requests, "
                "so no Reddit content will be fetched. "
                "To fix: create a Reddit app at https://www.reddit.com/prefs/apps "
                "(script type), then set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env. "
                "Until then, Reddit will be silently skipped."
            )
    
    def _check_praw(self) -> bool:
        """Check if PRAW library is available."""
        try:
            import praw
            return True
        except ImportError:
            return False
    
    async def fetch_posts(
        self,
        session: aiohttp.ClientSession,
        sort: str = "hot",
        limit: int = 25,
        time_filter: str = "day",
    ) -> List[RedditPost]:
        """
        Fetch posts from all configured subreddits.

        Args:
            session: aiohttp session
            sort: Sort method (hot, new, rising, top)
            limit: Max posts per subreddit
            time_filter: Time filter for top (hour, day, week, month, year, all)

        Returns:
            List of Reddit posts (empty if no API credentials configured)
        """
        # Early exit: without OAuth creds, Reddit 403s every request.
        # Avoid spamming the log with per-subreddit 403 warnings — the
        # init warning already told the user how to fix it.
        if not (self._client_id and self._client_secret):
            logger.debug("Reddit fetch skipped (no API credentials)")
            return []

        all_posts = []
        
        # Fetch from each subreddit concurrently
        tasks = [
            self._fetch_subreddit(session, sub, sort, limit, time_filter)
            for sub in self._subreddits
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_posts.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"Reddit fetch error: {result}")
        
        # Sort by score and deduplicate
        all_posts.sort(key=lambda p: p.score, reverse=True)
        
        seen_ids = set()
        unique_posts = []
        for post in all_posts:
            if post.id not in seen_ids:
                seen_ids.add(post.id)
                unique_posts.append(post)
        
        logger.info(f"Reddit: Fetched {len(unique_posts)} unique posts")
        return unique_posts
    
    async def _fetch_subreddit(
        self,
        session: aiohttp.ClientSession,
        subreddit: str,
        sort: str,
        limit: int,
        time_filter: str,
    ) -> List[RedditPost]:
        """Fetch posts from a single subreddit."""
        posts = []
        
        try:
            # Build URL for JSON API
            url = f"{self.BASE_URL}/r/{subreddit}/{sort}.json"
            params = {
                "limit": limit,
                "raw_json": 1,
            }
            if sort == "top":
                params["t"] = time_filter
            
            headers = {
                "User-Agent": self._user_agent,
            }
            
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    for child in data.get("data", {}).get("children", []):
                        try:
                            post = RedditPost.from_json(child, subreddit)
                            # Filter out non-link posts for news discovery
                            if post.title and len(post.title) > 10:
                                posts.append(post)
                        except Exception as e:
                            logger.debug(f"Error parsing post: {e}")
                
                elif response.status == 429:
                    logger.warning(f"Reddit rate limited for r/{subreddit}")
                else:
                    logger.warning(f"Reddit r/{subreddit}: HTTP {response.status}")
            
            # Small delay to respect rate limits
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.warning(f"Error fetching r/{subreddit}: {e}")
        
        return posts
    
    async def fetch_trending(
        self,
        session: aiohttp.ClientSession,
    ) -> List[str]:
        """
        Fetch trending topics from Reddit.
        
        Returns:
            List of trending topic strings
        """
        trending = []
        
        try:
            url = f"{self.BASE_URL}/api/trending_searches_v1.json"
            headers = {"User-Agent": self._user_agent}
            
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    trending = data.get("trending_searches", [])
        except Exception as e:
            logger.debug(f"Trending fetch error: {e}")
        
        return trending
    
    def get_available_subreddits(self) -> List[str]:
        """Get list of configured subreddits."""
        return self._subreddits.copy()


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def fetch_reddit_tech_posts(
    session: aiohttp.ClientSession = None,
    sort: str = "hot",
    limit: int = 25,
) -> List[RedditPost]:
    """
    Convenience function to fetch tech posts from Reddit.
    
    Args:
        session: Optional aiohttp session
        sort: Sort method (hot, new, rising, top)
        limit: Max posts per subreddit
    
    Returns:
        List of Reddit posts
    """
    client = RedditClient()
    
    if session is None:
        async with aiohttp.ClientSession() as session:
            return await client.fetch_posts(session, sort, limit)
    
    return await client.fetch_posts(session, sort, limit)
