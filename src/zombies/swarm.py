"""
Zombie Swarm — The Orchestrator.

Manages the lifecycle of all Zombie species. Assigns sources from the registry
to the appropriate zombie class, manages their background tasks, and provides
the unified callback for event ingestion.

Replaces CyclicSourceScheduler.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlsplit

from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor, SourceRegistry, SourceType
from src.storage.protocols import SourceHealthRepositoryProtocol

from .zombie_base import ZombieBase
from .z_corp import ZCorp
from .z_github import ZGitHub
from .z_hacker import ZHacker
from .z_rss import ZRss
from .z_security import ZSecurity
from .z_web import ZWeb

logger = logging.getLogger(__name__)

# Callback type for when a zombie discovers a new canonical observation
SourceObservationIngestionCallback = Callable[[SourceObservation], Awaitable[None]]


class ZombieSwarm:
    """Orchestrator for the entire Zombie ecosystem."""

    def __init__(
        self,
        registry: SourceRegistry,
        health_repository: Optional[SourceHealthRepositoryProtocol] = None,
    ):
        self.registry = registry
        self.health_repository = health_repository
        self._zombies: Dict[str, ZombieBase] = {}
        self._tasks: List[asyncio.Task] = []
        self._is_running = False
        self._ingestion_callback: Optional[SourceObservationIngestionCallback] = None

    def set_ingestion_callback(self, callback: SourceObservationIngestionCallback) -> None:
        """Set the callback that will receive new SourceObservations from all zombies."""
        self._ingestion_callback = callback

    async def hydrate_health(self) -> int:
        """
        Startup lifecycle operation to hydrate in-memory SourceDescriptors
        with persisted SourceHealth resilience states (cooldowns, failure counts).
        """
        if self.health_repository is None:
            logger.debug("No health_repository configured on ZombieSwarm; skipping hydration.")
            return 0

        records = await self.health_repository.get_all_health()
        hydrated = 0
        for h in records:
            desc = self.registry.get_source(h.source_id)
            if desc:
                desc.apply_source_health(h)
                hydrated += 1
        logger.info(f"🧟 Hydrated {hydrated} source resilience states from repository.")
        return hydrated

    async def record_hunt_outcome(
        self,
        source: SourceDescriptor,
        success: bool,
        tier_used: int = 0,
        article_count: int = 0,
        status_code: Optional[int] = None,
    ) -> None:
        """
        Update and persist the SourceHealth resilience state machine after a hunt attempt.
        """
        health = source.to_source_health()
        if success:
            health.record_success(working_tier=tier_used or source.last_working_tier)
        else:
            health.record_failure(status_code=status_code)

        source.apply_source_health(health)

        if self.health_repository is not None:
            try:
                await self.health_repository.save_health(health)
            except Exception as e:
                logger.error(f"Failed to persist health for source '{source.id}': {e}")

    async def flush_health(self) -> int:
        """
        Flush all current in-memory source health states to the repository.
        """
        if self.health_repository is None:
            return 0
        all_health = [desc.to_source_health() for desc in self.registry.get_all_ordered()]
        if not all_health:
            return 0
        try:
            return await self.health_repository.save_health_batch(all_health)
        except Exception as e:
            logger.error(f"Failed to flush source health batch during shutdown: {e}")
            return 0

    async def start(self) -> None:
        """Spawn all zombies and start hunting after hydrating health states."""
        if self._is_running:
            return
            
        if not self._ingestion_callback:
            raise RuntimeError("Cannot start ZombieSwarm without an ingestion callback.")

        self._is_running = True
        logger.info("🧟 Initializing Zombie Swarm...")

        # 0. Startup Hydration from SourceHealthRepository
        await self.hydrate_health()

        # 1. Spawn zombies for registered sources
        sources = self.registry.get_all_ordered()
        for source in sources:
            zombie = self._create_zombie_for_source(source)
            if zombie:
                self._zombies[source.id] = zombie

        # 2. Spawn specialized API zombies (not tied to standard sources)
        gh_source = SourceDescriptor(
            id="gh_api",
            url="https://api.github.com",
            name="GitHub Events",
            type=SourceType.API,
            tier=1,
            delay_seconds=180.0,
        )
        self._zombies["gh_api"] = ZGitHub(gh_source)
        
        hn_source = SourceDescriptor(
            id="hn_api",
            url="https://hacker-news.firebaseio.com",
            name="Hacker News API",
            type=SourceType.API,
            tier=1,
            delay_seconds=60.0,
        )
        self._zombies["hn_api"] = ZHacker(hn_source)

        logger.info(f"🧟 Swarm initialized with {len(self._zombies)} active zombies.")

        # 3. Start hunting tasks
        for zombie in self._zombies.values():
            task = asyncio.create_task(zombie.start_hunting(self._ingestion_callback))
            self._tasks.append(task)

    def stop(self) -> None:
        """Stop all zombies cleanly."""
        self._is_running = False
        for zombie in self._zombies.values():
            zombie.stop_hunting()
            
        for task in self._tasks:
            if not task.done():
                task.cancel()
                
        self._tasks.clear()
        logger.info("🧟 Zombie Swarm stopped.")

    async def aclose(self) -> None:
        """Asynchronously stop all zombies, flush health state, and cleanup network resources."""
        self.stop()
        close_tasks = [zombie.aclose() for zombie in self._zombies.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._zombies.clear()
        await self.flush_health()

    def _create_zombie_for_source(self, source: SourceDescriptor) -> Optional[ZombieBase]:
        """Factory method to instantiate the correct zombie species."""
        name_lower = source.name.lower()
        url_lower = source.url.lower()

        # Is it a corporate blog?
        corp_keywords = ["blog.google", "openai.com/blog", "microsoft.com", "apple.com", "meta.com", "engineering"]
        if any(k in url_lower for k in corp_keywords):
            return ZCorp(source)

        # Is it a security feed?
        sec_keywords = ["cve", "nvd", "security", "cisa", "cert", "vulnerability"]
        if any(k in name_lower or k in url_lower for k in sec_keywords):
            return ZSecurity(source)

        # Standard routing
        if source.type == SourceType.RSS:
            return ZRss(source)
        elif source.type == SourceType.HTML:
            return ZWeb(source)
        else:
            logger.warning(f"🧟 No standard zombie mapping for source type {source.type} on {source.name}")
            return None

    def trigger_feeding_frenzy(self, source_url: Optional[str] = None) -> None:
        """Force zombies to hunt immediately.
        
        If source_url is provided, safely matches the netloc domain to trigger matching zombies.
        Otherwise triggers all zombies.
        """
        if not source_url:
            for zombie in self._zombies.values():
                zombie.trigger_feeding_frenzy()
            return

        try:
            parsed = urlsplit(source_url)
            target_domain = (parsed.netloc or parsed.path or "").lower()
            if not target_domain:
                target_domain = source_url.lower()

            for zombie in self._zombies.values():
                try:
                    zombie_domain = urlsplit(zombie.source.url).netloc.lower()
                    if target_domain in zombie_domain or zombie_domain in target_domain:
                        zombie.trigger_feeding_frenzy()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error resolving domain from source_url '{source_url}': {e}")
