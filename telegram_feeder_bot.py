#!/usr/bin/env python3
"""
Telegram Feeder Bot — Lightweight Delivery Service for Tech News Scrapper.

A real-time parceling service that connects to the Main Engine server via
SSE (Server-Sent Events) for instant article delivery, with automatic
HTTP polling fallback if SSE disconnects.

Architecture:
  ┌─────────────────────┐       SSE / HTTP        ┌──────────────────┐
  │   Main Engine       │ ───────────────────────▶ │  Telegram Bot    │
  │   (Brain + Heart)   │   /api/v1/stream         │  (Delivery Hub)  │
  │   runs on server    │   /api/v1/feed           │  runs anywhere   │
  └─────────────────────┘                          └──────────────────┘
                                                          │
                                                          ▼
                                                   ┌──────────────┐
                                                   │   Telegram    │
                                                   │   Channel     │
                                                   └──────────────┘

Usage:
    # Connect to main engine and publish to Telegram
    python3 telegram_feeder_bot.py --engine-url http://server:8080

    # Test Telegram connection
    python3 telegram_feeder_bot.py --test

    # With explicit credentials
    python3 telegram_feeder_bot.py --token BOT_TOKEN --chat-id @channel
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
import logging
import os
import re
import signal
import ssl
import sys
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup

# Load .env file if available
ROOT_DIR = Path(__file__).resolve().parent
env_path = ROOT_DIR / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip("'\""))

# Import thumbnail resolver
try:
    from src.utils.thumbnail import resolve_og_thumbnail
except ImportError:
    resolve_og_thumbnail = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("TelegramFeederBot")

# Telegram limits
MAX_TELEGRAM_MSG_LEN = 4000  # Telegram API hard limit is 4096; leave headroom

# Defaults
DEFAULT_ENGINE_URL = "http://localhost:8080"
DEFAULT_POLL_INTERVAL = 60      # Fallback polling interval (seconds)
DEFAULT_QUEUE_SIZE = 300
DEFAULT_PUBLISH_DELAY = 1.5     # Seconds between Telegram publishes (rate limit)


# =============================================================================
# LIGHTWEIGHT ARTICLE — No heavy imports needed
# =============================================================================

@dataclass
class ArticleData:
    """Lightweight article data received from the engine API.
    No dependency on src.core.types — just plain data."""
    id: str
    url: str
    title: str
    summary: str = ""
    content: str = ""
    source: str = ""
    published_at: Optional[str] = None
    scraped_at: Optional[str] = None
    source_tier: Optional[int] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    pipeline: Optional[str] = None  # 'breaking' or 'standard'

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArticleData":
        return cls(
            id=data.get("id", ""),
            url=data.get("url", ""),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            content=data.get("content", ""),
            source=data.get("source", ""),
            published_at=data.get("published_at"),
            scraped_at=data.get("scraped_at"),
            source_tier=data.get("source_tier"),
            image_url=data.get("image_url"),
            category=data.get("category"),
            pipeline=data.get("pipeline"),
        )

    @property
    def is_breaking(self) -> bool:
        """Check if this article came from the breaking news pipeline."""
        return self.pipeline == "breaking"


# =============================================================================
# HTML / TEXT UTILITIES
# =============================================================================

def sanitize_title(title: str) -> str:
    """Sanitizes headline titles by stripping leading numbering or rank prefixes (e.g. '1. Headline', '1Headline', '15: Headline')."""
    if not title:
        return ""
    title = title.strip()
    # Strip list numbering with separators like '1. ', '1: ', '1) ', '1 - '
    title = re.sub(r'^\d{1,3}[\.\:\)\s\-]+\s*(?=[A-Za-z])', '', title)
    # Strip glued digits from headline start (e.g., '1Apple' -> 'Apple', keeping 3D, 5G, 4K, 2FA)
    title = re.sub(r'^\d{1,2}(?=[A-Z][a-z]{2,})', '', title)
    return title.strip()


def clean_html_text(raw_text: str) -> str:
    """Strips raw HTML tags, unescapes HTML entities, and cleans up RSS clutter."""
    if not raw_text:
        return ""

    text = html.unescape(raw_text)

    if "<" in text and ">" in text:
        soup = BeautifulSoup(text, "html.parser")
        lis = soup.find_all("li")
        if lis:
            lines = []
            for li in lis[:3]:
                t = li.get_text(" ", strip=True)
                t = re.sub(r"https?://\S+", "", t)
                t = re.sub(
                    r"\s+[a-zA-Z0-9.-]+\.(com|org|net|co|uk|gov|edu|io|google)\b.*$",
                    "", t, flags=re.IGNORECASE,
                )
                if t and len(t) > 10:
                    lines.append(f"• {t.strip()}")
            cleaned = "\n".join(lines)
        else:
            cleaned = soup.get_text("\n", strip=True)
    else:
        cleaned = text.strip()

    cleaned = re.sub(r"\[?&#\d+;\]?", "…", cleaned)
    cleaned = re.sub(r"\[?\.\.\.\]?", "…", cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines)


def _trim_to_html_budget(text: str, budget: int, suffix: str = "…") -> str:
    """Trim plain text so that html.escape(text) fits within `budget` characters."""
    if budget <= 0 or not text:
        return ""

    escaped_full = html.escape(text)
    if len(escaped_full) <= budget:
        return text

    budget_for_text = max(budget - len(suffix), 0)
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(html.escape(text[:mid])) <= budget_for_text:
            lo = mid
        else:
            hi = mid - 1

    return text[:lo].rstrip() + suffix


def generate_hashtags(title: str, category: Optional[str] = None) -> str:
    """Generates relevant tech hashtag badges for Telegram posts."""
    tags = set()
    t_lower = title.lower()

    if category:
        c_clean = re.sub(r'[^a-zA-Z0-9]', '', category)
        if c_clean and len(c_clean) > 2:
            tags.add(f"#{c_clean.capitalize()}")

    keywords_map = {
        "ai": "#AI", "artificial intelligence": "#AI", "llm": "#AI", "gpt": "#AI",
        "chatgpt": "#AI", "claude": "#AI", "gemini": "#AI", "nvidia": "#Nvidia",
        "apple": "#Apple", "iphone": "#Apple", "macbook": "#Apple", "ipad": "#Apple",
        "google": "#Google", "android": "#Android", "pixel": "#Google",
        "microsoft": "#Microsoft", "windows": "#Windows", "xbox": "#Gaming",
        "linux": "#Linux", "open source": "#OpenSource",
        "cybersecurity": "#Security", "vulnerability": "#Security", "hack": "#Security",
        "quantum": "#Quantum", "robot": "#Robotics", "robotics": "#Robotics",
        "spacex": "#Space", "nasa": "#Space", "satellite": "#Space",
        "dram": "#Hardware", "gpu": "#Hardware", "cpu": "#Hardware", "chip": "#Semiconductors",
        "samsung": "#Samsung", "foldable": "#Mobile", "smartphone": "#Mobile"
    }

    for kw, tag in keywords_map.items():
        if kw in t_lower:
            for single_tag in tag.split():
                tags.add(single_tag)

    if not tags:
        tags.add("#TechNews")

    return " ".join(sorted(list(tags))[:4])


# =============================================================================
# TELEGRAM PUBLISHER
# =============================================================================

class TelegramPublisher:
    """Async Telegram Bot client with retry logic, photo support, and HTML message formatting."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        self.photo_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        self._session: Optional[aiohttp.ClientSession] = None

    def _create_connector(self) -> aiohttp.TCPConnector:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:
            pass
        return aiohttp.TCPConnector(ssl=ctx)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = self._create_connector()
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _decode_google_news_url(self, url: str) -> str:
        """Decodes Google News RSS redirect URLs to extract the actual publisher URL."""
        if "news.google.com/rss/articles/" not in url:
            return url

        try:
            b64_part = url.split("news.google.com/rss/articles/")[1].split("?")[0]
            b64_part += "=" * (-len(b64_part) % 4)
            decoded_bytes = base64.urlsafe_b64decode(b64_part)
            decoded_str = decoded_bytes.decode("utf-8", errors="ignore")

            match = re.search(r"https?://[^\s<>\"'\\]+", decoded_str)
            if match:
                return match.group(0)
        except Exception:
            pass

        return url

    def format_article_message(self, article: ArticleData, max_len: int = MAX_TELEGRAM_MSG_LEN, has_thumbnail: bool = True) -> str:
        """Formats an ArticleData into a rich, high-engagement Telegram HTML broadcast layout."""
        raw_title = sanitize_title(clean_html_text(article.title)) if article.title else "Untitled"
        raw_title = _trim_to_html_budget(raw_title, 250)
        title = html.escape(raw_title)

        # Decode Google News URL for proper Rich Preview
        raw_url = (article.url or "").strip()
        if "news.google.com/rss/articles/" in raw_url:
            raw_url = self._decode_google_news_url(raw_url)
        url = html.escape(raw_url)

        # 🔴 Header
        if article.is_breaking:
            header = (
                "🔴🔴🔴 <b>BREAKING NEWS</b> 🔴🔴🔴\n\n"
                f"⚡ <b>{title}</b>\n"
            )
        else:
            if has_thumbnail:
                header = f"📰 <b>{title}</b>\n"
            else:
                # Add more engaging emojis when there is no thumbnail
                header = f"🚀✨ <b>{title}</b> 💡🔥\n"

        # Add hashtags for interactive elements if no thumbnail
        hashtags = generate_hashtags(article.title, article.category) if not has_thumbnail else ""
        hashtag_str = f"\n🏷️ {hashtags}" if hashtags else ""
        
        footer = f"{hashtag_str}\n🔗 <a href=\"{url}\">Read Original Article</a>" if url else f"{hashtag_str}"

        raw_summary = (article.summary or "").strip()
        cleaned_summary = clean_html_text(raw_summary)

        # Suppress synthetic/placeholder summaries or title repetitions
        lower_sum = cleaned_summary.lower().strip()
        lower_title = raw_title.lower().strip()

        # Fuzzy title-vs-summary dedup using character overlap ratio
        def _similarity(a: str, b: str) -> float:
            if not a or not b:
                return 0.0
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if shorter in longer:
                return 1.0
            common = sum(1 for c in shorter if c in longer)
            return common / max(len(longer), 1)

        is_duplicate_summary = (
            lower_sum == lower_title
            or lower_title in lower_sum
            or _similarity(lower_title, lower_sum) > 0.75
        )
        is_placeholder = any(lower_sum.startswith(p) for p in [
            "scraped from", "extracted realtime via", "scraped via", "extracted via",
            "scraped", "extracted", "no summary", "n/a", "none"
        ])

        if is_placeholder or len(cleaned_summary) < 20 or is_duplicate_summary:
            cleaned_summary = ""

        has_summary = bool(cleaned_summary)

        raw_content = (article.content or "").strip()
        cleaned_content = clean_html_text(raw_content)
        include_content = (
            bool(cleaned_content)
            and len(cleaned_content) > 50
            and cleaned_content.lower() != cleaned_summary.lower()
            and raw_title.lower() not in cleaned_content.lower()[:len(raw_title) + 20]
        )

        msg = header
        reserved = len(msg) + len(footer) + 50

        if has_summary:
            summary_header = "\n💡 <b>Key Highlights:</b>\n"
            
            # More budget for summary when there is no thumbnail
            if has_thumbnail:
                summary_budget = 400 if max_len <= 1024 else (1000 if include_content else (max_len - reserved - len(summary_header)))
            else:
                summary_budget = 800 if max_len <= 1024 else (1500 if include_content else (max_len - reserved - len(summary_header)))
                
            summary_budget = max(summary_budget, 80)

            trimmed_summary = _trim_to_html_budget(cleaned_summary, summary_budget)
            if trimmed_summary:
                msg += summary_header + html.escape(trimmed_summary) + "\n"

        if include_content and max_len > 1024:
            content_header = "\n📄 <b>Overview:</b>\n"
            content_budget = max_len - len(msg) - len(content_header) - len(footer) - 20
            content_budget = max(content_budget, 100)

            trimmed_content = _trim_to_html_budget(cleaned_content, content_budget)
            if trimmed_content:
                msg += content_header + html.escape(trimmed_content) + "\n"

        msg += footer

        # Safety trim to prevent 400 API errors
        if len(msg) > max_len:
            footer_idx = msg.rfind("\n🔗")
            if footer_idx != -1:
                body = msg[:footer_idx]
                footer_part = msg[footer_idx:]
                allowed_body_len = max_len - len(footer_part) - 10
                body = body[:allowed_body_len]

                last_amp = body.rfind('&')
                last_semi = body.rfind(';')
                if last_amp > last_semi:
                    body = body[:last_amp]

                msg = body + "...\n" + footer_part
            else:
                msg = msg[:max_len - 10] + "..."

        return msg

    async def publish_article(self, article: ArticleData) -> bool:
        """Publishes article to Telegram using sendPhoto if image_url exists or can be resolved, falling back to sendMessage."""
        img_url = article.image_url

        if img_url and (img_url.startswith("http://") or img_url.startswith("https://")):
            caption = self.format_article_message(article, max_len=1000, has_thumbnail=True)
            success = await self.send_photo(img_url, caption)
            if success:
                return True
            logger.info("Falling back to text message for article delivery...")

        msg = self.format_article_message(article, max_len=MAX_TELEGRAM_MSG_LEN, has_thumbnail=False)
        return await self.send_message(msg)

    async def send_photo(self, photo_url: str, caption: str, retries: int = 2) -> bool:
        """Sends photo message to Telegram with caption."""
        if not self.bot_token or not self.chat_id:
            return False

        payload = {
            "chat_id": self.chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        }

        for attempt in range(1, retries + 1):
            try:
                session = await self.get_session()
                async with session.post(self.photo_url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Article photo published to Telegram ({self.chat_id})")
                        return True

                    try:
                        res_json = await resp.json()
                    except Exception:
                        res_json = {}
                    error_desc = res_json.get("description", f"HTTP {resp.status}")

                    if resp.status == 429:
                        retry_after = res_json.get("parameters", {}).get("retry_after", 5)
                        await asyncio.sleep(float(retry_after))
                        continue

                    logger.warning(f"⚠️ Telegram sendPhoto warning ({resp.status}): {error_desc}")
                    break
            except Exception as exc:
                logger.warning(f"⚠️ sendPhoto failed (attempt {attempt}/{retries}): {exc}")

        return False

    async def send_message(self, text: str, retries: int = 3) -> bool:
        """Sends HTML formatted message to Telegram with retry and fallback."""
        if not self.bot_token or not self.chat_id:
            logger.error("Telegram bot token or chat ID is missing.")
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        for attempt in range(1, retries + 1):
            try:
                session = await self.get_session()
                async with session.post(self.api_url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"✅ Article published to Telegram ({self.chat_id})")
                        return True

                    try:
                        res_json = await resp.json()
                    except Exception:
                        res_json = {}
                    error_desc = res_json.get("description", f"HTTP {resp.status}")

                    if resp.status == 429:
                        retry_after = res_json.get("parameters", {}).get("retry_after", 5)
                        try:
                            retry_after = float(retry_after)
                        except (TypeError, ValueError):
                            retry_after = 5.0
                        logger.warning(f"⚠️ Rate limit hit. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue

                    if (
                        resp.status == 400
                        and "parse entities" in error_desc.lower()
                        and payload.get("parse_mode")
                    ):
                        logger.warning("⚠️ HTML rejected, retrying as plain text...")
                        plain_text = html.unescape(re.sub(r"<[^>]+>", "", payload["text"])) #type:ignore
                        payload = {
                            "chat_id": self.chat_id,
                            "text": plain_text,
                            "disable_web_page_preview": False,
                        }
                        continue

                    logger.error(f"❌ Telegram API Error ({resp.status}): {error_desc}")
                    break

            except Exception as exc:
                exc_str = str(exc)
                logger.warning(f"⚠️ Request failed (attempt {attempt}/{retries}): {exc}")
                if attempt < retries:
                    await asyncio.sleep(2 * attempt)

        return False


# =============================================================================
# FEEDER BOT — SSE Real-Time + HTTP Polling Fallback
# =============================================================================

class FeederBot:
    """Real-time delivery service: connects to Main Engine, publishes to Telegram.

    Primary mode: SSE (Server-Sent Events) for instant push delivery.
    Fallback mode: HTTP polling every `poll_interval` seconds if SSE disconnects.
    """

    def __init__(
        self,
        publisher: TelegramPublisher,
        engine_url: str = DEFAULT_ENGINE_URL,
        api_key: Optional[str] = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        publish_delay: float = DEFAULT_PUBLISH_DELAY,
    ):
        self.publisher = publisher
        self.engine_url = engine_url.rstrip("/")
        self.api_key = api_key or os.getenv("ENGINE_API_KEY")
        self.poll_interval = poll_interval
        self.publish_delay = publish_delay

        self.queue: asyncio.Queue[ArticleData] = asyncio.Queue(maxsize=queue_size)
        self.publish_queue: asyncio.Queue[ArticleData] = asyncio.Queue(maxsize=queue_size)
        
        self._seen_ids_file = ROOT_DIR / "cache" / "seen_telegram_ids.txt"
        self._max_seen = 10000
        self._seen_ids: dict = self._load_seen_ids()

        self._running = False
        self._stop_event = asyncio.Event()
        self._publisher_task: Optional[asyncio.Task] = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._prepare_task: Optional[asyncio.Task] = None

        # Stats
        self._articles_received = 0
        self._articles_published = 0
        self._sse_connected = False
        self._last_server_time: Optional[str] = None

    def _load_seen_ids(self) -> dict:
        """Load previously seen IDs from disk to prevent duplicates on restart."""
        seen = {}
        if self._seen_ids_file.exists():
            try:
                with open(self._seen_ids_file, "r") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped:
                            seen[stripped] = True
            except Exception as e:
                logger.error(f"Failed to load seen IDs: {e}")

        # Truncate if the file accumulated too many entries across restarts
        if len(seen) > self._max_seen:
            keys = list(seen.keys())
            seen = {k: True for k in keys[-self._max_seen // 2:]}
            # Rewrite the truncated file
            try:
                self._seen_ids_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self._seen_ids_file, "w") as f:
                    for k in seen:
                        f.write(f"{k}\n")
                logger.info(f"Truncated seen_ids file from {len(keys)} to {len(seen)} entries on load.")
            except Exception:
                pass

        return seen

    def _is_new(self, article_id: str) -> bool:
        """Check if article ID hasn't been seen before."""
        if article_id in self._seen_ids:
            return False
        self._seen_ids[article_id] = True
        
        # Persist to disk
        try:
            self._seen_ids_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._seen_ids_file, "a") as f:
                f.write(f"{article_id}\n")
        except Exception:
            pass
            
        # Prevent unbounded memory growth
        if len(self._seen_ids) > self._max_seen:
            # dict keys preserve insertion order in Python 3.7+
            keys = list(self._seen_ids.keys())
            to_keep = keys[-self._max_seen // 2:]
            self._seen_ids = {k: True for k in to_keep}
            
            # Rewrite file with truncated list
            try:
                with open(self._seen_ids_file, "w") as f:
                    for k in to_keep:
                        f.write(f"{k}\n")
            except Exception:
                pass
                
        return True

    def _enqueue(self, article: ArticleData) -> None:
        """Enqueue article for publishing with quality pre-check."""
        if not article.url or not article.title:
            return
        if not self._is_new(article.id):
            return

        # Pre-check: require title with at least 4 words (reject nav links)
        title_words = [w for w in (article.title or "").split() if len(w) > 1]
        if len(title_words) < 4:
            logger.debug(f"Skipped (short title): '{article.title}'")
            return

        self._articles_received += 1
        title_preview = (article.title or "Untitled")[:60]

        try:
            self.queue.put_nowait(article)
            logger.info(f"📥 Queued: '{title_preview}...' [{article.source}]")
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(article)
                logger.warning(f"⚠️ Queue full — dropped oldest to enqueue: '{title_preview}...'")
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                logger.error("Queue full and could not make room.")

    # ── SSE Receiver (Primary) ──

    async def _sse_receiver(self) -> None:
        """Connect to Main Engine SSE stream for real-time article push."""
        stream_url = f"{self.engine_url}/api/v1/stream"
        backoff = 2

        while self._running:
            try:
                logger.info(f"📡 Connecting to SSE stream: {stream_url}")
                timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
                req_headers = {}
                if self.api_key:
                    req_headers["X-API-Key"] = self.api_key

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(stream_url, headers=req_headers if req_headers else None) as resp:
                        if resp.status != 200:
                            logger.warning(f"SSE connection failed: HTTP {resp.status}")
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 60)
                            continue

                        self._sse_connected = True
                        backoff = 2  # Reset backoff on successful connect
                        logger.info("✓ SSE stream connected — receiving real-time articles")

                        async for raw_line in resp.content:
                            if not self._running:
                                break
                            line = raw_line.decode("utf-8", errors="ignore").strip()

                            if line.startswith("data: "):
                                data_str = line[6:]
                                try:
                                    data = json.loads(data_str)
                                    if "id" in data and "title" in data:
                                        article = ArticleData.from_dict(data)
                                        self._enqueue(article)
                                except json.JSONDecodeError:
                                    pass

                        # Stream ended — reconnect
                        self._sse_connected = False
                        logger.warning("SSE stream ended. Reconnecting...")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._sse_connected = False
                logger.warning(f"SSE error: {exc}. Falling back to polling, retry in {backoff}s...")
                # Fall back to HTTP polling while SSE is down
                await self._poll_once()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # ── HTTP Poll Fallback ──

    async def _poll_once(self) -> None:
        """Single HTTP poll to /api/v1/feed for articles."""
        feed_url = f"{self.engine_url}/api/v1/feed"
        params = {"limit": "100"}
        if self._last_server_time:
            params["since"] = self._last_server_time

        req_headers = {}
        if self.api_key:
            req_headers["X-API-Key"] = self.api_key

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(feed_url, params=params, headers=req_headers if req_headers else None) as resp:
                    if resp.status != 200:
                        logger.warning(f"Poll failed: HTTP {resp.status}")
                        return

                    data = await resp.json()
                    articles = data.get("articles", [])
                    self._last_server_time = data.get("server_time")

                    for art_dict in articles:
                        article = ArticleData.from_dict(art_dict)
                        self._enqueue(article)

                    if articles:
                        logger.info(f"📡 Polled {len(articles)} articles from engine")

        except Exception as exc:
            logger.warning(f"Poll error: {exc}")

    # ── Prepare Loop ──
    
    async def _prepare_loop(self) -> None:
        """Consume articles from initial queue, try to fetch thumbnails, then pass to publish queue."""
        while self._running:
            try:
                article = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                
                title_preview = (article.title or 'Untitled')[:60]
                img_url = article.image_url

                # Try to resolve thumbnail if missing
                if not img_url and resolve_og_thumbnail and article.url:
                    try:
                        session = await self.publisher.get_session()
                        # Use a slightly longer timeout since this isn't blocking publishing of other articles directly
                        img_url = await resolve_og_thumbnail(article.url, session=session, timeout_seconds=4.0)
                        if img_url:
                            article.image_url = img_url
                    except Exception as e:
                        logger.debug(f"Failed to fetch thumbnail for {article.url}: {e}")
                        img_url = None

                # Forward to publish queue
                try:
                    self.publish_queue.put_nowait(article)
                except asyncio.QueueFull:
                    logger.warning(f"⚠️ Publish queue full — dropped article: '{title_preview}...'")
                
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Prepare loop error: {exc}")
                await asyncio.sleep(2.0)

    # ── Publisher Loop ──

    async def _publish_loop(self) -> None:
        """Consume articles from publish queue, enforce summary, and publish.

        Pipeline-aware delays:
        - Breaking articles: 1.5s delay (immediate delivery)
        - Standard articles: 120s delay (2-minute gaps)
        """
        while self._running:
            try:
                article = await asyncio.wait_for(self.publish_queue.get(), timeout=1.0)

                title_preview = (article.title or 'Untitled')[:60]

                summary = (article.summary or "").strip()
                
                # Check if summary is just the title repeated (fuzzy dedup)
                title_lower = (article.title or "").lower().strip()
                summary_lower = summary.lower().strip()
                if title_lower == summary_lower or (
                    title_lower in summary_lower and len(summary) - len(article.title) < 30
                ):
                    logger.info(f"⏭️ Skipped (summary = title): '{title_preview}...' [{article.source}]")
                    self.publish_queue.task_done()
                    continue

                # ── PUBLISH ──
                success = await self.publisher.publish_article(article)
                if success:
                    self._articles_published += 1
                    # Log message without implying we skipped anything if it succeeded
                self.publish_queue.task_done()

                # Pipeline-aware publish delay
                if article.is_breaking:
                    await asyncio.sleep(self.publish_delay)  # Fast: 1.5s default
                else:
                    await asyncio.sleep(120.0)  # Standard: 2-minute gap

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Publish loop error: {exc}")
                await asyncio.sleep(2.0)

    # ── Lifecycle ──

    async def start(self) -> None:
        """Start the feeder bot."""
        self._running = True
        self._stop_event.clear()

        logger.info("═" * 60)
        logger.info("  Telegram Feeder Bot — Delivery Service Starting")
        logger.info(f"  Engine: {self.engine_url}")
        logger.info(f"  Channel: {self.publisher.chat_id}")
        logger.info("═" * 60)

        # Check engine health first
        health_ok = await self._check_engine_health()
        if not health_ok:
            logger.warning("⚠️ Engine not reachable — will keep retrying in background")
        else:
            # Fetch initially buffered articles
            logger.info("Fetching initially buffered articles...")
            await self._poll_once()

        # Start publisher, preparer and SSE receiver
        self._publisher_task = asyncio.create_task(self._publish_loop())
        self._prepare_task = asyncio.create_task(self._prepare_loop())
        self._receiver_task = asyncio.create_task(self._sse_receiver())

        logger.info("✓ Feeder Bot is LIVE — delivering articles to Telegram")

        await self._stop_event.wait()

    async def _check_engine_health(self) -> bool:
        """Check if the main engine is reachable."""
        health_url = f"{self.engine_url}/api/v1/health"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(health_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"✓ Engine connected — {data.get('buffer', {}).get('buffered', 0)} articles buffered")
                        return True
        except Exception as exc:
            logger.warning(f"Engine health check failed: {exc}")
        return False

    async def stop(self) -> None:
        """Stop the feeder bot gracefully."""
        if not self._running:
            return
        logger.info("🛑 Stopping Feeder Bot...")
        self._running = False
        self._stop_event.set()

        for task in [self._receiver_task, self._publisher_task, self._prepare_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self.publisher.close()
        logger.info(
            f"👋 Feeder Bot stopped. "
            f"Received: {self._articles_received}, Published: {self._articles_published}"
        )


# =============================================================================
# TEST MODE
# =============================================================================

async def run_test(publisher: TelegramPublisher, engine_url: str):
    """Send a verification test message and optionally check engine connectivity."""
    logger.info("🧪 Running Telegram + Engine connectivity test...")

    # Test engine connection
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"{engine_url}/api/v1/health") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"✓ Engine reachable — status: {data.get('status')}, "
                                f"buffered: {data.get('buffer', {}).get('buffered', 0)}")
                else:
                    logger.warning(f"⚠️ Engine returned HTTP {resp.status}")
    except Exception as exc:
        logger.warning(f"⚠️ Engine not reachable at {engine_url}: {exc}")

    # Test Telegram
    test_msg = (
        "🤖 <b>Tech News Scrapper Bot Online!</b>\n\n"
        "✅ <i>Telegram Feeder Bot connected and ready to deliver articles.</i>\n\n"
        f"🔗 Engine: <code>{html.escape(engine_url)}</code>"
    )
    success = await publisher.send_message(test_msg)
    await publisher.close()
    if success:
        logger.info("🎉 Test message delivered to Telegram!")
    else:
        logger.error("❌ Test message failed. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        sys.exit(1)


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

async def main_async(args):
    token = args.token.strip()
    chat_id = args.chat_id.strip()

    if not token:
        logger.error("Missing Telegram Bot Token. Set TELEGRAM_BOT_TOKEN in .env or pass --token.")
        sys.exit(1)

    if not chat_id and not args.test:
        logger.error("Missing Telegram Chat ID. Set TELEGRAM_CHAT_ID in .env or pass --chat-id.")
        sys.exit(1)

    publisher = TelegramPublisher(bot_token=token, chat_id=chat_id)

    if args.test:
        if not chat_id:
            logger.error("Test mode requires a valid TELEGRAM_CHAT_ID.")
            sys.exit(1)
        await run_test(publisher, args.engine_url)
        return

    bot = FeederBot(
        publisher=publisher,
        engine_url=args.engine_url,
        api_key=args.api_key,
        poll_interval=args.poll_interval,
        queue_size=args.queue_size,
        publish_delay=args.publish_delay,
    )

    loop = asyncio.get_running_loop()

    def _handle_signal():
        task = asyncio.create_task(bot.stop())
        task.add_done_callback(
            lambda t: t.exception() and logger.error(f"Shutdown error: {t.exception()}")
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    try:
        await bot.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Keyboard interrupt received.")
        await bot.stop()


def main():
    parser = argparse.ArgumentParser(
        description="Telegram Feeder Bot — Delivery Service for Tech News Scrapper"
    )
    parser.add_argument(
        "--token", type=str,
        default=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        help="Telegram Bot Token (or set TELEGRAM_BOT_TOKEN env var)",
    )
    parser.add_argument(
        "--chat-id", type=str,
        default=os.getenv("TELEGRAM_CHAT_ID", ""),
        help="Telegram Chat ID or @channel (or set TELEGRAM_CHAT_ID env var)",
    )
    parser.add_argument(
        "--engine-url", type=str,
        default=os.getenv("ENGINE_API_URL", DEFAULT_ENGINE_URL),
        help=f"Main Engine API URL (default: {DEFAULT_ENGINE_URL})",
    )
    parser.add_argument(
        "--api-key", type=str,
        default=os.getenv("ENGINE_API_KEY", ""),
        help="Main Engine API key (or set ENGINE_API_KEY env var)",
    )
    parser.add_argument(
        "--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL,
        help=f"HTTP poll fallback interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--queue-size", type=int, default=DEFAULT_QUEUE_SIZE,
        help=f"Max articles buffered before oldest is dropped (default: {DEFAULT_QUEUE_SIZE})",
    )
    parser.add_argument(
        "--publish-delay", type=float, default=DEFAULT_PUBLISH_DELAY,
        help=f"Seconds between Telegram publishes (default: {DEFAULT_PUBLISH_DELAY})",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test Telegram + Engine connectivity and exit",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()