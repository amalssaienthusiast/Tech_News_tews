"""
CyclicSourceScheduler - Continuous Daemon Queue Scheduler.

Replaces fragmented gather-all batch crawling loops with an asyncio.Queue round-robin queue.
Process flow per source:
BypassResolver.fetch -> Extract -> DedupGate -> QualityGate -> FeedChain.push (IMMEDIATE)
"""

import asyncio
from datetime import datetime, UTC
import hashlib
import logging
from typing import Any, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import feedparser

from ..core.types import Article, SourceTier
from .source_registry import SourceRegistry, SourceDescriptor, SourceType
from ..bypass.bypass_resolver import BypassResolver
from .dedup_gate import DedupGate
from .quality_gate import QualityGate
from .feed_chain import FeedChain
from ..utils.text import sanitize_title

logger = logging.getLogger(__name__)

class CyclicSourceScheduler:
    """
    Continuous round-robin queue scheduler for source ingestion.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        bypass: BypassResolver,
        dedup: DedupGate,
        quality: QualityGate,
        feed: FeedChain,
        concurrency: int = 1
    ):
        self.registry = registry
        self.bypass = bypass
        self.dedup = dedup
        self.quality = quality
        self.feed = feed
        self.concurrency = concurrency

        self._queue: asyncio.Queue[SourceDescriptor] = asyncio.Queue()
        self._running = False
        self._workers: List[asyncio.Task] = []

    async def start(self) -> None:
        """Seed queue with ordered sources and start worker daemon tasks."""
        if self._running:
            return

        self._running = True
        sources = self.registry.get_all_ordered()
        for src in sources:
            self._queue.put_nowait(src)

        logger.info(f"CyclicSourceScheduler started with {len(sources)} sources and concurrency={self.concurrency}")
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self.concurrency)]

    def stop(self) -> None:
        """Stop worker tasks cleanly."""
        self._running = False
        for w in self._workers:
            if not w.done():
                w.cancel()
        logger.info("CyclicSourceScheduler stopped.")

    async def _worker(self, worker_id: int) -> None:
        """Daemon worker loop for get -> process -> sleep -> re-enqueue."""
        while self._running:
            try:
                source = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                # Check cooldown backoff
                now = datetime.now(UTC)
                if source.cooldown_until and source.cooldown_until > now:
                    logger.debug(f"Worker {worker_id}: Source {source.name} in cooldown until {source.cooldown_until.isoformat()}. Skipping.")
                else:
                    await self._process_one_source(source)
            except Exception as e:
                logger.error(f"Worker {worker_id}: Exception processing source {source.name}: {e}")
            finally:
                await asyncio.sleep(max(1.0, source.delay_seconds))
                if self._running:
                    self._queue.put_nowait(source)
                self._queue.task_done()

    async def _process_one_source(self, source: SourceDescriptor) -> None:
        """
        Single-source pipeline execution:
        Fetch -> Extract -> DedupGate -> QualityGate -> FeedChain.push
        """
        logger.info(f"🔄 Processing source: {source.name} ({source.url}) [Type: {source.type.value}]")

        # 1. Fetch content via BypassResolver escalation ladder
        content = await self.bypass.fetch(source, max_budget_seconds=20.0)
        if not content:
            logger.warning(f"Failed to fetch content for source {source.name}")
            self.registry.record_result(source.id, success=False, tier_used=source.last_working_tier, article_count=0)
            return

        # 2. Extract raw articles based on SourceType
        articles = self._extract_articles(source, content)
        if not articles:
            logger.debug(f"No articles extracted from source {source.name}")
            self.registry.record_result(source.id, success=True, tier_used=source.last_working_tier, article_count=0)
            return

        pushed_count = 0
        for article in articles:
            # 3. Dedup Gate check
            if self.dedup.check_and_add(article):
                continue  # Reject duplicate

            # 4. Quality Gate check
            if not self.quality.check(article):
                continue  # Reject quality/timeliness failure

            # 5. Push instantly to FeedChain subscribers
            await self.feed.push(article)
            pushed_count += 1

        logger.info(f"✓ Source {source.name}: {len(articles)} raw -> {pushed_count} new articles pushed to FeedChain")
        self.registry.record_result(source.id, success=True, tier_used=source.last_working_tier, article_count=pushed_count)

    def _extract_articles(self, source: SourceDescriptor, content: str) -> List[Article]:
        """Type-aware article extractor (RSS / HTML)."""
        articles: List[Article] = []

        if source.type == SourceType.RSS:
            try:
                feed = feedparser.parse(content)
                for entry in feed.entries[:25]:
                    url = getattr(entry, "link", None)
                    title = getattr(entry, "title", None)
                    clean_title = sanitize_title(title)
                    if not url or not clean_title:
                        continue

                    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
                    article_id = hashlib.md5(url.strip().encode("utf-8")).hexdigest()

                    # Robust date parsing (handles RSS published_parsed and Atom updated_parsed)
                    pub_date = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            pub_date = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                        except Exception:
                            pass
                    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                        try:
                            pub_date = datetime(*entry.updated_parsed[:6], tzinfo=UTC)
                        except Exception:
                            pass
                    elif hasattr(entry, "created_parsed") and entry.created_parsed:
                        try:
                            pub_date = datetime(*entry.created_parsed[:6], tzinfo=UTC)
                        except Exception:
                            pass

                    image_url = self._extract_rss_image(entry, summary)

                    articles.append(Article(
                        id=article_id,
                        url=url,
                        title=clean_title,
                        content=summary.strip(),
                        summary=summary.strip()[:300],
                        source=source.name,
                        source_tier=SourceTier.TIER_2 if source.tier <= 2 else SourceTier.TIER_3,
                        published_at=pub_date,
                        image_url=image_url,
                    ))
            except Exception as e:
                logger.error(f"Error parsing RSS feed for {source.name}: {e}")

        elif source.type == SourceType.HTML:
            try:
                soup = BeautifulSoup(content, "html.parser")

                # Remove nav, footer, header, aside, and script elements FIRST
                # to prevent extracting navigation links as articles
                for junk_el in soup.find_all(["nav", "footer", "header", "aside", "script", "style", "noscript"]):
                    junk_el.decompose()

                selector = source.link_selector or "article a, h2 a, h3 a, .title a, a.title, .headline a, .post-title a, .story a, .entry-title a"
                links = soup.select(selector)

                # REMOVED: the dangerous fallback that scraped ALL <a> tags.
                # If no structured selector matches, this source has no articles.

                for link in links[:25]:
                    href = link.get("href")
                    raw_title = link.get_text(strip=True)
                    clean_title = sanitize_title(raw_title)
                    if not href or not clean_title:
                        continue

                    # CRITICAL: Require 6+ words — real headlines are sentences,
                    # not "Programming" or "Memory and Storage"
                    title_words = [w for w in clean_title.split() if len(w) > 1]
                    if len(title_words) < 6:
                        continue

                    # Reject bracket-wrapped titles like "[Annals of Internal Medicine]"
                    if clean_title.startswith("[") or clean_title.startswith("{"):
                        continue

                    # Reject garbled HTML concatenation (words > 40 chars)
                    if any(len(w) > 40 for w in clean_title.split()):
                        continue

                    # Reject navigation-like text
                    lower_title = clean_title.lower()
                    if any(lower_title.startswith(p) for p in ("view more", "read more", "see all", "see more", "load more")):
                        continue

                    full_url = urljoin(source.url, href)
                    article_id = hashlib.md5(full_url.encode("utf-8")).hexdigest()

                    articles.append(Article(
                        id=article_id,
                        url=full_url,
                        title=clean_title,
                        content="",
                        summary="",
                        source=source.name,
                        source_tier=SourceTier.TIER_3,
                        published_at=None
                    ))
            except Exception as e:
                logger.error(f"Error extracting HTML articles for {source.name}: {e}")

        return articles

    def _extract_rss_image(self, entry: Any, summary: str = "") -> Optional[str]:
        """Extracts article thumbnail image URL from feed entry or description HTML."""
        # 1. Check media_content
        media_content = getattr(entry, "media_content", None)
        if media_content and isinstance(media_content, list):
            for item in media_content:
                if isinstance(item, dict) and item.get("url"):
                    if item.get("medium") == "image" or item.get("type", "").startswith("image/") or not item.get("type"):
                        return item["url"]

        # 2. Check media_thumbnail
        media_thumbnail = getattr(entry, "media_thumbnail", None)
        if media_thumbnail and isinstance(media_thumbnail, list):
            for item in media_thumbnail:
                if isinstance(item, dict) and item.get("url"):
                    return item["url"]

        # 3. Check enclosures
        enclosures = getattr(entry, "enclosures", None)
        if enclosures and isinstance(enclosures, list):
            for enc in enclosures:
                if isinstance(enc, dict) and enc.get("href"):
                    if enc.get("type", "").startswith("image/"):
                        return enc["href"]

        # 4. Check BeautifulSoup <img> tags in summary or content
        raw_html = summary
        if hasattr(entry, "content") and isinstance(entry.content, list):
            for c in entry.content:
                if isinstance(c, dict) and c.get("value"):
                    raw_html += " " + c["value"]

        if "<img" in raw_html.lower():
            try:
                soup = BeautifulSoup(raw_html, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if src and src.startswith("http") and not any(skip in src.lower() for skip in ["tracker", "pixel", "feedburner", "1x1", "icon"]):
                        return src
            except Exception:
                pass

        return None
