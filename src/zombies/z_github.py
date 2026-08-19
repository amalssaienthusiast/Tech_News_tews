"""
Z-GITHUB — GitHub Event Zombie Species.

Hunts for technology events on GitHub:
- New releases from major tracked repositories (Linux, Kubernetes, React, etc.)
- Security advisories (GHSA)
- Trending repositories

Uses the GitHub REST API. Uses If-None-Match to respect rate limits.
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, UTC
import logging
import os
from typing import Dict, List, Optional

import aiohttp

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor
from .zombie_base import ZombieBase

logger = logging.getLogger(__name__)

# Max concurrent API requests to avoid rate-limit spikes
_GITHUB_CONCURRENCY = 5

# Tracked repositories for major releases
TRACKED_REPOS = [
    "torvalds/linux",
    "kubernetes/kubernetes",
    "nodejs/node",
    "facebook/react",
    "python/cpython",
    "golang/go",
    "rust-lang/rust",
    "microsoft/vscode",
    "microsoft/TypeScript",
    "tensorflow/tensorflow",
    "pytorch/pytorch",
    "huggingface/transformers",
    "docker/cli",
    "apple/swift",
]


class ZGitHub(ZombieBase):
    """GitHub hunting zombie."""
    
    species = ZombieSpecies.GITHUB

    def __init__(self, source: SourceDescriptor):
        super().__init__(source)
        self.token = os.environ.get("GITHUB_TOKEN")
        self._etags: Dict[str, str] = {}
        # Bounded seen IDs index (FIFO eviction over 1000 entries)
        self._seen_ids: OrderedDict[str, bool] = OrderedDict()
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(_GITHUB_CONCURRENCY)
        self._timeout = aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=10)

    def _resolve_tier(self) -> SourceTier:
        if self.source.tier <= 1:
            return SourceTier.TIER_1_PREMIUM
        return SourceTier.TIER_2_SPECIALIST

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Tech-Zombie-Swarm",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create the long-lived session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self._get_headers(),
                timeout=self._timeout,
            )
        return self._session

    async def hunt(self) -> List[SourceObservation]:
        """Hunt for GitHub events (Releases, Advisories) in parallel."""
        new_sources: List[SourceObservation] = []
        session = await self._ensure_session()

        # Parallelize release checks across all tracked repos
        release_tasks = [
            self._check_releases(session, repo) for repo in TRACKED_REPOS
        ]
        # Also check advisories in the same batch
        advisory_task = self._check_advisories(session)

        results = await asyncio.gather(*release_tasks, advisory_task, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Z-GITHUB parallel task error: {result}")
                continue
            if isinstance(result, list):
                new_sources.extend(result)

        return new_sources

    async def _check_releases(self, session: aiohttp.ClientSession, repo: str) -> List[SourceObservation]:
        """Check for new releases in a specific repository (with concurrency limit)."""
        async with self._semaphore:
            url = f"https://api.github.com/repos/{repo}/releases"
            headers = {}
            if url in self._etags:
                headers["If-None-Match"] = self._etags[url]

            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 304:
                        return []  # Not modified
                    if resp.status == 403:
                        logger.warning("Z-GITHUB hit rate limit.")
                        return []
                    if resp.status != 200:
                        return []

                    if "ETag" in resp.headers:
                        self._etags[url] = resp.headers["ETag"]

                    data = await resp.json()
                    new_events: List[SourceObservation] = []
                    tier = self._resolve_tier()
                    
                    # Only look at the latest 3 releases
                    for release in data[:3]:
                        release_id = str(release.get("id"))
                        if release_id in self._seen_ids:
                            continue
                            
                        tag_name = release.get("tag_name", "")
                        name = release.get("name", "")
                        html_url = release.get("html_url", "")
                        published_at_str = release.get("published_at")
                        body = release.get("body", "")

                        if not html_url or not published_at_str:
                            continue
                            
                        # Build headline
                        project_name = repo.split("/")[-1].title()
                        display_name = name if name and name != tag_name else tag_name
                        headline = f"{project_name} releases {display_name}"

                        pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                        if pub_date.tzinfo is None:
                            pub_date = pub_date.replace(tzinfo=UTC)
                        else:
                            pub_date = pub_date.astimezone(UTC)

                        source_obs = SourceObservation.create(
                            source_id=self.source.id,
                            source_name=self.source.name or "GitHub Releases",
                            source_tier=tier,
                            zombie_species=self.species,
                            url=html_url,
                            title=headline,
                            raw_content="",
                            summary=body[:500],
                            published_at_hint=pub_date,
                            metadata={
                                "event_type": "release",
                                "repo": repo,
                                "tag": tag_name,
                                "is_primary": True,
                            },
                        )
                        new_events.append(source_obs)
                        self._seen_ids[release_id] = True
                        if len(self._seen_ids) > 1000:
                            self._seen_ids.popitem(last=False)
                        
                    return new_events

            except Exception as e:
                logger.debug(f"Z-GITHUB error checking releases for {repo}: {e}")
                return []

    async def _check_advisories(self, session: aiohttp.ClientSession) -> List[SourceObservation]:
        """Check GitHub Global Security Advisories."""
        async with self._semaphore:
            url = "https://api.github.com/advisories"
            headers = {}
            if url in self._etags:
                headers["If-None-Match"] = self._etags[url]

            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 304 or resp.status != 200:
                        return []
                        
                    if "ETag" in resp.headers:
                        self._etags[url] = resp.headers["ETag"]

                    data = await resp.json()
                    new_events: List[SourceObservation] = []
                    tier = self._resolve_tier()
                    
                    for advisory in data[:10]:
                        ghsa_id = advisory.get("ghsa_id")
                        if not ghsa_id or ghsa_id in self._seen_ids:
                            continue
                            
                        summary = advisory.get("summary", "")
                        html_url = advisory.get("html_url", "")
                        published_at_str = advisory.get("published_at")
                        severity = advisory.get("severity", "unknown")
                        
                        if not html_url or not published_at_str or severity not in ["high", "critical"]:
                            continue

                        headline = f"Security Advisory: {summary} ({ghsa_id})"
                        pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                        if pub_date.tzinfo is None:
                            pub_date = pub_date.replace(tzinfo=UTC)
                        else:
                            pub_date = pub_date.astimezone(UTC)

                        source_obs = SourceObservation.create(
                            source_id=self.source.id,
                            source_name=self.source.name or "GitHub Security Advisory",
                            source_tier=tier,
                            zombie_species=self.species,
                            url=html_url,
                            title=headline,
                            raw_content="",
                            summary=advisory.get("description", "")[:500],
                            published_at_hint=pub_date,
                            metadata={
                                "event_type": "advisory",
                                "ghsa_id": ghsa_id,
                                "severity": severity,
                                "is_primary": True,
                            },
                        )
                        new_events.append(source_obs)
                        self._seen_ids[ghsa_id] = True
                        if len(self._seen_ids) > 1000:
                            self._seen_ids.popitem(last=False)
                        
                    return new_events
            except Exception as e:
                logger.debug(f"Z-GITHUB error checking advisories: {e}")
                return []

    async def aclose(self) -> None:
        """Asynchronous cleanup for the network session."""
        await super().aclose()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

