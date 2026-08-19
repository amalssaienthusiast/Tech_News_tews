"""
Configuration settings for the Tech News Scraper application.

This module contains all configurable parameters for the application,
including paths, timing, API keys, and model settings. Environment
variables are used for sensitive values like API keys.
"""

import os
from pathlib import Path
from typing import Any, Dict, List

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # dotenv not installed, rely on system env vars

# =============================================================================
# DIRECTORY CONFIGURATION
# =============================================================================

# Base directory (project root)
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Directory paths
DATA_DIR: Path = BASE_DIR / "data"
LOGS_DIR: Path = BASE_DIR / "logs"
CACHE_DIR: Path = BASE_DIR / "cache"
SOURCES_DIR: Path = BASE_DIR / "discovered_sources"

# Create directories if they don't exist
for directory in [DATA_DIR, LOGS_DIR, CACHE_DIR, SOURCES_DIR]:
    directory.mkdir(exist_ok=True)

# =============================================================================
# FILE PATHS
# =============================================================================

# Legacy JSON files (kept for migration support)
OUTPUT_FILE: Path = DATA_DIR / "tech_news_ai.json"
DISCOVERED_SOURCES_FILE: Path = SOURCES_DIR / "discovered_sources.json"
URL_CACHE_FILE: Path = CACHE_DIR / "url_cache_ai.json"

# SQLite database file
DB_FILE: Path = DATA_DIR / "tech_news.db"

# =============================================================================
# SCRAPING SETTINGS
# =============================================================================

# Time intervals (in seconds)
CHECK_INTERVAL: int = 3600  # 1 hour between scrape cycles
MAX_AGE_HOURS: int = 72     # Only fetch articles within 72 hours
MAX_RETRIES: int = 3        # Retry count for failed requests
RETRY_DELAY: int = 5        # Initial retry delay (doubles each retry)
MAX_WORKERS: int = 5        # Max concurrent scraping tasks

# Rate limiting
SOURCE_SCRAPE_DELAY: float = 2.0      # Delay between sources (sync mode)
ARTICLE_SCRAPE_DELAY: float = 1.0     # Delay between articles (sync mode)
DISCOVERY_RATE_LIMIT: float = 2.0     # Discovery requests per second

# Token bucket rate limiter settings
RATE_LIMIT_TOKENS_PER_SECOND: float = 2.0  # Refill rate
RATE_LIMIT_BUCKET_SIZE: int = 10           # Max burst capacity

# User agent for HTTP requests
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# =============================================================================
# TECH KEYWORDS
# =============================================================================

# Keywords for source discovery and validation
TECH_KEYWORDS: List[str] = [
    "technology", "tech", "artificial intelligence", "AI", "machine learning",
    "software", "hardware", "cybersecurity", "blockchain", "cloud computing",
    "programming", "coding", "data science", "robotics", "IoT", "5G",
    "quantum computing", "virtual reality", "augmented reality", "startup",
    "innovation", "digital", "computer", "electronics", "semiconductor",
    "neural network", "deep learning", "automation", "API", "SaaS",
    "open source", "developer", "DevOps", "infrastructure", "microservices"
]

# =============================================================================
# DISCOVERY CONFIGURATION
# =============================================================================

# Search queries for discovering new tech news sources
DISCOVERY_QUERIES: List[str] = [
    "latest technology news",
    "tech news websites",
    "artificial intelligence news",
    "software development news",
    "cybersecurity news today",
    "tech startups news",
    "programming news",
    "cloud computing updates",
    "machine learning articles",
    "data science blog",
]

# Global topics for auto-discovery
GLOBAL_TOPICS: List[str] = [
    "Artificial Intelligence",
    "Machine Learning",
    "Cybersecurity",
    "Blockchain",
    "Cloud Computing",
    "Data Science",
    "Internet of Things",
    "5G Technology",
    "Quantum Computing",
    "Virtual Reality",
    "Augmented Reality",
    "Robotics",
    "Software Engineering",
    "Web Development",
    "Mobile App Development",
    "DevOps",
    "Big Data",
    "Cryptocurrency",
    "Tech Startups",
    "Consumer Electronics",
    # Science & Research (NEW)
    "Physics",
    "Biology",
    "Chemistry",
    "Neuroscience",
    "Biotechnology",
    "Space Exploration",
    "Climate Science",
    "Materials Science",
    "Genetics",
    "Nuclear Fusion",
]

# =============================================================================
# DEFAULT SOURCES
# =============================================================================

# Curated default sources (always available)
DEFAULT_SOURCES: List[Dict[str, Any]] = [
    {
        "url": "https://techcrunch.com/feed/",
        "type": "rss",
        "name": "TechCrunch",
        "verified": True
    },
    {
        "url": "https://feeds.feedburner.com/thenextweb",
        "type": "rss",
        "name": "The Next Web",
        "verified": True
    },
    {
        "url": "https://www.theverge.com/rss/index.xml",
        "type": "rss",
        "name": "The Verge",
        "verified": True
    },
    {
        "url": "https://www.wired.com/feed/rss",
        "type": "rss",
        "name": "Wired",
        "verified": True
    },
    {
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "type": "rss",
        "name": "Ars Technica",
        "verified": True
    },
]

# =============================================================================
# AI MODEL SETTINGS
# =============================================================================

# Summarization model (HuggingFace)
SUMMARIZATION_MODEL: str = "sshleifer/distilbart-cnn-6-6"
SUMMARY_MAX_LENGTH: int = 100
SUMMARY_MIN_LENGTH: int = 30
MAX_CONTENT_FOR_SUMMARY: int = 1500

# Semantic search model (Sentence Transformers)
SEARCH_MODEL: str = "all-MiniLM-L6-v2"

# =============================================================================
# API KEYS (from environment variables)
# =============================================================================

# Google Custom Search API
# Get your API key: https://developers.google.com/custom-search/v1/overview
# Create CSE: https://programmablesearchengine.google.com/
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID: str = os.getenv("GOOGLE_CSE_ID", "")

# Bing Search API
# Get your API key: https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
BING_API_KEY: str = os.getenv("BING_API_KEY", "")

# =============================================================================
# GUI SETTINGS
# =============================================================================

GUI_WIDTH: int = 1200
GUI_HEIGHT: int = 800
STATS_UPDATE_INTERVAL: int = 5000   # 5 seconds
LOG_POLL_INTERVAL: int = 100        # 100ms

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# =============================================================================
# BYPASS SETTINGS
# =============================================================================

# Anti-bot bypass settings
ENABLE_ANTI_BOT_BYPASS: bool = True
CLOUDFLARE_WAIT_TIMEOUT: int = 30  # seconds to wait for Cloudflare challenge
HUMAN_SIMULATION_MIN_DELAY: float = 0.5  # min seconds for human-like delay
HUMAN_SIMULATION_MAX_DELAY: float = 2.0  # max seconds for human-like delay
MAX_BYPASS_RETRIES: int = 3  # max retries for bypass attempts

# Paywall bypass settings
ENABLE_PAYWALL_BYPASS: bool = True
DEFAULT_PAYWALL_METHOD: str = "auto"  # auto, incognito, google_cache, archive_today, referer_spoof
PAYWALL_SELECTORS: List[str] = [
    ".paywall",
    ".subscription-wall",
    "[data-paywall]",
    ".premium-content",
    ".metered-content",
    ".gate",
    ".modal-overlay",
    ".subscribe-wall",
]

# Proxy settings
PROXY_ENABLED: bool = False
PROXY_LIST: List[str] = []  # Add your proxies: ["http://proxy1:8080", "socks5://proxy2:1080"]
PROXY_ROTATION_INTERVAL: int = 10  # requests before automatic proxy rotation
PROXY_HEALTH_CHECK_INTERVAL: int = 300  # seconds between health checks
PROXY_MAX_FAILURES: int = 3  # failures before marking proxy unhealthy

# Browser automation settings (Playwright)
USE_BROWSER_AUTOMATION: bool = False  # Enable for advanced bypass (requires Playwright)
BROWSER_HEADLESS: bool = True  # Run browser in headless mode
BROWSER_TIMEOUT: int = 30000  # milliseconds

# =============================================================================
# INTELLIGENCE SETTINGS (v3.0)
# =============================================================================

# LLM Provider Configuration
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "hybrid")  # gemini, langchain, local, hybrid
LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-1.5-flash")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_FALLBACK_ENABLED: bool = True

# Disruption Analysis Settings
DISRUPTION_ANALYSIS_ENABLED: bool = True
DEFAULT_INDUSTRY_CONTEXT: str = "Technology"
MAX_ANALYSIS_CONTENT_LENGTH: int = 4000  # Max chars to send to LLM

# Alert Thresholds (criticality scores 1-10)
ALERT_CRITICAL_THRESHOLD: int = 9   # 🔴 Critical alerts
ALERT_HIGH_THRESHOLD: int = 7       # 🟠 High priority
ALERT_MEDIUM_THRESHOLD: int = 4     # 🟡 Medium priority
ALERT_ENABLED: bool = True

# Alert Channel Configuration (GUI-only by default)
# Other channels can be configured via the GUI
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "")

# Directory Scraper Settings (Enterprise throughput)
DIRECTORY_SCRAPE_ENABLED: bool = True
DIRECTORY_MAX_ARTICLES_PER_HOUR: int = 2000
DIRECTORY_CONCURRENT_SCRAPERS: int = 10
DIRECTORY_SCRAPE_INTERVAL: int = 300  # 5 minutes

# Google Custom Search Integration
GOOGLE_SEARCH_ENABLED: bool = bool(GOOGLE_API_KEY and GOOGLE_CSE_ID)
GOOGLE_SEARCH_DAILY_LIMIT: int = 10000
GOOGLE_SEARCH_FOR_DISCOVERY: bool = True
GOOGLE_SEARCH_FOR_ARTICLES: bool = True
GOOGLE_SEARCH_FOR_TRENDS: bool = True

# Intelligence Categories (loaded from config/categories.yaml)
CATEGORIES_CONFIG_PATH: Path = BASE_DIR / "config" / "categories.yaml"
INDUSTRIES_CONFIG_PATH: Path = BASE_DIR / "config" / "industries.yaml"

# =============================================================================
# REDIS CONFIGURATION (Real-Time Infrastructure)
# =============================================================================

# Redis connection
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_PUBSUB_CHANNEL: str = "news:realtime"
REDIS_CACHE_TTL: int = 300  # 5 minutes cache TTL

# Redis connection pool settings
REDIS_MAX_CONNECTIONS: int = 10
REDIS_SOCKET_TIMEOUT: int = 5
REDIS_RETRY_ON_TIMEOUT: bool = True

# =============================================================================
# ADDITIONAL SEARCH ENGINE APIS
# =============================================================================

# NewsAPI.org (70,000+ sources)
# Get your API key: https://newsapi.org/
NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")
NEWSAPI_ENABLED: bool = bool(NEWSAPI_KEY)
NEWSAPI_RATE_LIMIT: int = 100  # requests per day (free tier)

# SerpAPI (Google/Bing search results)
# Get your API key: https://serpapi.com/
SERPAPI_KEY: str = os.getenv("SERPAPI_KEY", "")
SERPAPI_ENABLED: bool = bool(SERPAPI_KEY)

# Reddit API (r/news, r/technology, etc.)
# Register app: https://www.reddit.com/prefs/apps
REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "TechNewsScraper/1.0")
REDDIT_ENABLED: bool = bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)

# =============================================================================
# REAL-TIME FEEDER SETTINGS
# =============================================================================

# Refresh intervals (in seconds)
REALTIME_REFRESH_INTERVAL: int = 300  # Full source scraping cycle every 5 minutes (300 seconds)

REALTIME_COLD_REFRESH_INTERVAL: int = 300  # Cold sources refresh (5 min)
REALTIME_DISCOVERY_INTERVAL: int = 600  # New source discovery (10 min)

# Real-time feed capacity
REALTIME_MAX_ARTICLES: int = 500
REALTIME_MAX_AGE_HOURS: int = 24
REALTIME_SOURCES_PER_REFRESH: int = 10  # Parallel source fetches

# =============================================================================
# WEBSOCKET SETTINGS
# =============================================================================

WEBSOCKET_HOST: str = os.getenv("WEBSOCKET_HOST", "0.0.0.0")
WEBSOCKET_PORT: int = int(os.getenv("WEBSOCKET_PORT", "8765"))
WEBSOCKET_HEARTBEAT_INTERVAL: int = 30  # seconds
WEBSOCKET_MAX_CONNECTIONS: int = 1000
WEBSOCKET_MESSAGE_QUEUE_SIZE: int = 100

# =============================================================================
# DEDUPLICATION SETTINGS
# =============================================================================

DEDUP_BLOOM_EXPECTED_ITEMS: int = 100_000
DEDUP_BLOOM_FP_RATE: float = 0.01
DEDUP_TITLE_SIMILARITY_THRESHOLD: float = 0.90  # 90% similarity = duplicate
DEDUP_USE_SEMANTIC: bool = True  # Use sentence transformers for semantic dedup