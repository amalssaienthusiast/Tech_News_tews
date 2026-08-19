"""
Z-HACKER — Hacker News Firebase API Zombie Species.

Hunts for high-velocity stories on Hacker News using the official Firebase API.
Bypasses the RSS feed to get real-time story creation and score velocity.
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, UTC
import logging
from typing import Dict, List, Optional

import aiohttp

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor
from src.utils.text import sanitize_title
from .zombie_base import ZombieBase

logger = logging.getLogger(__name__)

HN_FIREBASE_BASE = "https://hacker-news.firebaseio.com/v0"


class ZHacker(ZombieBase):
    """Hacker News hunting zombie."""
    
    species = ZombieSpecies.HACKER_NEWS

    def __init__(self, source: SourceDescriptor):
        super().__init__(source)
        # Bounded seen IDs index (FIFO eviction over 2000 entries)
        self._seen_ids: OrderedDict[int, bool] = OrderedDict()
        self._score_cache: OrderedDict[int, int] = OrderedDict()  # id -> last_score
        self._time_cache: OrderedDict[int, datetime] = OrderedDict()  # id -> last_checked
        self._session: Optional[aiohttp.ClientSession] = None
        self._timeout = aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=10)
        self._semaphore = asyncio.Semaphore(10)  # Max 10 concurrent story fetches

    def _resolve_tier(self) -> SourceTier:
        if self.source.tier <= 1:
            return SourceTier.TIER_1_PREMIUM
        return SourceTier.TIER_2_SPECIALIST

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create the long-lived session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def hunt(self) -> List[SourceObservation]:
        """Check topstories and newstories for high-velocity items."""
        new_sources: List[SourceObservation] = []
        session = await self._ensure_session()

        # Get current top and new stories
        top_ids = await self._fetch_list(session, "topstories")
        new_ids = await self._fetch_list(session, "newstories")

        # We want to check the top 30 and the newest 30
        target_ids = list(set(top_ids[:30] + new_ids[:30]))

        # Fetch all stories in parallel (with concurrency limit)
        async def _fetch_one(story_id: int) -> Optional[dict]:
            async with self._semaphore:
                return await self._fetch_item(session, story_id)

        results = await asyncio.gather(
            *[_fetch_one(sid) for sid in target_ids],
            return_exceptions=True,
        )

        now = datetime.now(UTC)
        tier = self._resolve_tier()

        for story_id, story in zip(target_ids, results):
            if isinstance(story, Exception) or not story or story.get("type") != "story":
                continue

            url = story.get("url")
            title = story.get("title")
            score = story.get("score", 0)
            time_val = story.get("time")

            if not url or not title or not time_val:
                continue

            # Velocity check
            is_high_velocity = False

            if story_id in self._score_cache:
                prev_score = self._score_cache[story_id]
                prev_time = self._time_cache[story_id]
                time_diff_min = max(1.0, (now - prev_time).total_seconds() / 60.0)
                score_diff = score - prev_score
                velocity = score_diff / time_diff_min

                # If gaining more than 2 points per minute, it's hot
                if velocity > 2.0 and score > 20:
                    is_high_velocity = True

            self._score_cache[story_id] = score
            self._time_cache[story_id] = now
            if len(self._score_cache) > 500:
                self._score_cache.popitem(last=False)
                self._time_cache.popitem(last=False)

            # Only yield if we haven't seen it, OR if it just became high velocity
            if story_id not in self._seen_ids or is_high_velocity:
                clean_title = sanitize_title(title)
                pub_date = datetime.fromtimestamp(time_val, tz=UTC)

                # If we're yielding it because of velocity, we already saw it
                if story_id in self._seen_ids and not is_high_velocity:
                    continue

                source_obs = SourceObservation.create(
                    source_id=self.source.id,
                    source_name=self.source.name or "Hacker News",
                    source_tier=tier,
                    zombie_species=self.species,
                    url=url,
                    title=clean_title,
                    raw_content="",
                    summary=f"HN Score: {score}",
                    published_at_hint=pub_date,
                    metadata={
                        "hn_item_id": story_id,
                        "hn_score": score,
                        "high_velocity": is_high_velocity,
                    },
                )
                new_sources.append(source_obs)
                self._seen_ids[story_id] = True
                if len(self._seen_ids) > 2000:
                    self._seen_ids.popitem(last=False)

        return new_sources

    async def _fetch_list(self, session: aiohttp.ClientSession, list_name: str) -> List[int]:
        try:
            async with session.get(f"{HN_FIREBASE_BASE}/{list_name}.json") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.debug(f"ZHacker list fetch error: {e}")
        return []

    async def _fetch_item(self, session: aiohttp.ClientSession, item_id: int) -> Optional[dict]:
        try:
            async with session.get(f"{HN_FIREBASE_BASE}/item/{item_id}.json") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.debug(f"ZHacker item fetch error: {e}")
        return None

    async def aclose(self) -> None:
        """Asynchronous cleanup for the network session."""
        await super().aclose()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
