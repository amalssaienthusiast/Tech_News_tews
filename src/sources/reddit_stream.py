"""
Reddit Streaming Client - Phase 2: Social Firehose
Implements PRAW streaming for real-time Reddit monitoring
"""

import asyncio
import logging
import ssl
from typing import Optional, Callable, List, Dict, Set
from datetime import datetime, UTC
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _make_ssl_context():
    """Create an SSL context using certifi CA bundle (fixes macOS SSL errors)."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except ImportError:
        return None  # aiohttp will use its own default — may fail on macOS without certifi


@dataclass
class RedditStreamConfig:
    """Configuration for Reddit streaming"""
    subreddits: List[str]  # List of subreddits to monitor
    min_score: int = 10  # Minimum upvote score to report
    skip_self_posts: bool = True  # Skip text-only posts
    skip_stickied: bool = True  # Skip stickied/pinned posts
    poll_interval: float = 1.0  # Seconds between polls (PRAW handles this)


class RedditStreamClient:
    """
    Real-time Reddit streaming client using PRAW.
    Provides millisecond-level news detection from social media.
    """
    
    # Tech subreddits to monitor
    DEFAULT_SUBREDDITS = [
        "technology",
        "programming",
        "machinelearning",
        "artificial",
        "startups",
        "cybersecurity",
        "netsec",
        "devops",
        "datascience",
        "webdev",
        "computerscience",
        "tech",
        "gadgets",
        "hardware",
        "software",
    ]
    
    def __init__(self, 
                 client_id: Optional[str] = None,
                 client_secret: Optional[str] = None,
                 user_agent: str = "TechNewsScraper/7.0 (Global Discovery Agent)",
                 config: Optional[RedditStreamConfig] = None):
        """
        Initialize Reddit streaming client.
        
        Args:
            client_id: Reddit API client ID (optional, uses public API if not provided)
            client_secret: Reddit API client secret (optional)
            user_agent: User agent string for API requests
            config: Streaming configuration
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.config = config or RedditStreamConfig(subreddits=self.DEFAULT_SUBREDDITS)
        
        # State
        self._running = False
        self._stream_task: Optional[asyncio.Task] = None
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._seen_ids: Set[str] = set()  # Deduplication
        self._stats = {
            "posts_streamed": 0,
            "posts_filtered": 0,
            "start_time": None,
        }
        
        # Callbacks
        self.on_new_post: Optional[Callable[[Dict], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        
        # PRAW instance (initialized on start)
        self._reddit = None
        
        logger.info(f"🔴 Reddit Stream Client initialized")
        logger.info(f"   Subreddits: {len(self.config.subreddits)}")
        logger.info(f"   Min score: {self.config.min_score}")
        
    def _init_praw(self) -> bool:
        """Initialize PRAW instance if credentials available"""
        try:
            import praw

            if not self.client_id or not self.client_secret:
                # Reddit's public JSON API now 403s unauthenticated requests
                # (tightened mid-2024). The JSON fallback would just spam 403s,
                # so we log ONE clear actionable warning at start and skip the
                # stream entirely.
                logger.warning(
                    "⚠️ No Reddit API credentials — Reddit stream disabled. "
                    "Reddit's public JSON API now 403s unauthenticated requests. "
                    "To enable: create a Reddit app at https://www.reddit.com/prefs/apps "
                    "(script type), then set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env."
                )
                return False

            self._reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )

            # Test connection
            self._reddit.user.me()
            logger.info("✅ Reddit API authenticated successfully")
            return True

        except ImportError:
            logger.error("❌ PRAW not installed. Run: pip install praw")
            return False
        except Exception as e:
            logger.error(f"❌ Reddit API authentication failed: {e}")
            return False
    
    async def start(self):
        """Start streaming from Reddit"""
        if self._running:
            logger.warning("Reddit stream already running")
            return
            
        self._running = True
        self._stats["start_time"] = datetime.now(UTC)
        
        # Initialize PRAW
        if self._init_praw():
            # Use PRAW streaming (authenticated)
            self._stream_task = asyncio.create_task(self._stream_praw())
        elif not (self.client_id and self.client_secret):
            # No credentials — skip the stream entirely. The init warning
            # already told the user how to fix it. The JSON fallback would
            # just 403 on every request (Reddit tightened their public API
            # in mid-2024).
            logger.info("🔴 Reddit stream not started (no API credentials)")
            self._running = False
            return
        else:
            # Credentials set but PRAW unavailable — fall back to JSON polling
            self._stream_task = asyncio.create_task(self._stream_json_fallback())
            
        logger.info("🔴 Reddit stream started")
        
    async def stop(self):
        """Stop streaming"""
        self._running = False
        
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
                
        self._executor.shutdown(wait=False)
        logger.info("🔴 Reddit stream stopped")
        
    async def _stream_praw(self):
        """Stream using PRAW (authenticated, real-time)"""
        try:
            # Create multireddit of all subreddits
            subreddit_str = "+".join(self.config.subreddits)
            multireddit = self._reddit.subreddit(subreddit_str)
            
            logger.info(f"📡 Streaming from r/{subreddit_str}")
            
            # Stream submissions
            for submission in multireddit.stream.submissions(skip_existing=True):
                if not self._running:
                    break
                    
                try:
                    await self._process_submission(submission)
                except Exception as e:
                    logger.error(f"Error processing submission: {e}")
                    if self.on_error:
                        await self._call_error_handler(e)
                        
        except Exception as e:
            logger.error(f"PRAW stream error: {e}")
            if self.on_error:
                await self._call_error_handler(e)
                
    async def _stream_json_fallback(self):
        """Fallback to JSON API polling (unauthenticated)"""
        import aiohttp
        
        logger.info("📡 Using JSON API fallback (polling every 30s)")
        
        while self._running:
            try:
                for subreddit in self.config.subreddits[:5]:  # Limit to top 5 for fallback
                    await self._poll_subreddit(subreddit)
                    await asyncio.sleep(6)  # Rate limiting
                    
                await asyncio.sleep(30)  # Poll every 30 seconds
                
            except Exception as e:
                logger.error(f"JSON poll error: {e}")
                await asyncio.sleep(60)
                
    async def _poll_subreddit(self, subreddit: str):
        """Poll a subreddit using JSON API"""
        import aiohttp

        url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=25"
        headers = {"User-Agent": self.user_agent}

        # Bug fix: use certifi SSL context to avoid SSLCertVerificationError on macOS
        ssl_ctx = _make_ssl_context()

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, ssl=ssl_ctx) as response:
                if response.status == 200:
                    data = await response.json()
                    posts = data.get("data", {}).get("children", [])

                    for post_data in posts:
                        post = post_data.get("data", {})
                        if self._should_process_post(post):
                            await self._emit_post(self._convert_post(post))
                            
    async def _process_submission(self, submission):
        """Process a PRAW submission object"""
        # Extract data
        post = {
            "id": submission.id,
            "title": submission.title,
            "url": f"https://reddit.com{submission.permalink}",
            "external_url": submission.url if not submission.is_self else None,
            "subreddit": submission.subreddit.display_name,
            "author": str(submission.author) if submission.author else "[deleted]",
            "score": submission.score,
            "num_comments": submission.num_comments,
            "created_utc": datetime.fromtimestamp(submission.created_utc, tz=UTC),
            "is_self": submission.is_self,
            "selftext": submission.selftext[:500] if submission.is_self else "",
            "stickied": submission.stickied,
        }
        
        # Check filters
        if not self._should_process_post(post):
            self._stats["posts_filtered"] += 1
            return
            
        # Deduplication
        if post["id"] in self._seen_ids:
            return
        self._seen_ids.add(post["id"])
        
        # Emit
        await self._emit_post(post)
        
    def _should_process_post(self, post: Dict) -> bool:
        """Check if post passes filters"""
        # Skip if below minimum score
        if post.get("score", 0) < self.config.min_score:
            return False
            
        # Skip self posts if configured
        if self.config.skip_self_posts and post.get("is_self", False):
            return False
            
        # Skip stickied posts if configured
        if self.config.skip_stickied and post.get("stickied", False):
            return False
            
        return True
        
    def _convert_post(self, post: Dict) -> Dict:
        """Convert JSON API post to standard format"""
        return {
            "id": post.get("id"),
            "title": post.get("title"),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "external_url": post.get("url") if not post.get("is_self") else None,
            "subreddit": post.get("subreddit"),
            "author": post.get("author"),
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "created_utc": datetime.fromtimestamp(post.get("created_utc", 0), tz=UTC),
            "is_self": post.get("is_self", False),
            "selftext": post.get("selftext", "")[:500],
            "stickied": post.get("stickied", False),
        }
        
    async def _emit_post(self, post: Dict):
        """Emit post to callback"""
        self._stats["posts_streamed"] += 1
        
        if self.on_new_post:
            try:
                if asyncio.iscoroutinefunction(self.on_new_post):
                    await self.on_new_post(post)
                else:
                    self.on_new_post(post)
            except Exception as e:
                logger.error(f"Error in post callback: {e}")
                
    async def _call_error_handler(self, error: Exception):
        """Call error handler"""
        if self.on_error:
            try:
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(error)
                else:
                    self.on_error(error)
            except Exception as e:
                logger.error(f"Error in error handler: {e}")
                
    def get_stats(self) -> Dict:
        """Get streaming statistics"""
        runtime = 0
        if self._stats["start_time"]:
            runtime = (datetime.now(UTC) - self._stats["start_time"]).total_seconds()
            
        return {
            "posts_streamed": self._stats["posts_streamed"],
            "posts_filtered": self._stats["posts_filtered"],
            "runtime_seconds": runtime,
            "posts_per_minute": (self._stats["posts_streamed"] / runtime * 60) if runtime > 0 else 0,
            "seen_ids_count": len(self._seen_ids),
            "is_running": self._running,
            "mode": "PRAW" if self._reddit else "JSON-Fallback",
        }


# Global singleton
_reddit_stream_client: Optional[RedditStreamClient] = None


def get_reddit_stream_client(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    user_agent: str = "TechNewsScraper/7.0"
) -> RedditStreamClient:
    """Get or create Reddit stream client singleton"""
    global _reddit_stream_client
    if _reddit_stream_client is None:
        _reddit_stream_client = RedditStreamClient(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent
        )
    return _reddit_stream_client


# Example usage
if __name__ == "__main__":
    async def test():
        client = get_reddit_stream_client()
        
        # Callback when new post arrives
        async def on_post(post):
            print(f"\n🔴 r/{post['subreddit']}: {post['title'][:60]}...")
            print(f"   Score: {post['score']} | Comments: {post['num_comments']}")
            if post['external_url']:
                print(f"   Link: {post['external_url']}")
                
        client.on_new_post = on_post
        
        # Start streaming
        await client.start()
        
        # Run for 60 seconds
        await asyncio.sleep(60)
        
        # Show stats
        print("\n📊 Reddit Stream Stats:")
        for key, value in client.get_stats().items():
            print(f"   {key}: {value}")
            
        # Stop
        await client.stop()
    
    asyncio.run(test())
