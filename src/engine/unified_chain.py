"""
Unified Feed Chain Singleton Container & Entry Point.

Centralizes the Unified Feed Chain:
SourceRegistry -> ZombieSwarm -> CanonicalPipelineRunner (Phase 3).
"""

import asyncio
import logging
import os
from typing import Any, Callable, List, Optional, Union, TYPE_CHECKING

from ..core.types import Article
from .source_registry import SourceRegistry, SourceDescriptor
from ..bypass.bypass_resolver import BypassResolver
from .publication_bus import get_publication_bus, PublicationBus
from ..domain.enums import PublicationChannel, PublicationEventType, PublicationPriority
from ..domain.models import PublicationEvent, SourceObservation

# TYPE_CHECKING-only imports break the circular dependency at runtime
# while still allowing static analysis / IDE type hints.
if TYPE_CHECKING:
    from ..zombies.swarm import ZombieSwarm
    from ..pipeline.runner import CanonicalPipelineRunner
    from ..storage.protocols import ArticleRepositoryProtocol, EventRepositoryProtocol, SourceHealthRepositoryProtocol

logger = logging.getLogger(__name__)


def get_pipeline_mode() -> str:
    """
    Resolve active pipeline mode with authoritative precedence:
    1. CANONICAL_PIPELINE_MODE env var ('active', 'shadow', 'legacy')
    2. ENABLE_CANONICAL_PIPELINE env var (True -> 'active', False -> 'legacy')
    Defaults to 'active' in production.
    """
    mode = os.environ.get("CANONICAL_PIPELINE_MODE", "").lower().strip()
    if mode in ("active", "shadow", "legacy"):
        return mode
    enable_flag = os.environ.get("ENABLE_CANONICAL_PIPELINE")
    if enable_flag is not None:
        cleaned = enable_flag.lower().strip()
        if cleaned in ("false", "0", "no"):
            return "legacy"
        if cleaned in ("true", "1", "yes"):
            return "active"
    return "active"


class UnifiedFeedChainEngine:
    """
    Singleton engine managing the Unified Feed Chain lifecycle.
    Orchestrates SourceRegistry, ZombieSwarm, and CanonicalPipelineRunner.
    """

    def __init__(
        self,
        event_repository: Optional["EventRepositoryProtocol"] = None,
        article_repository: Optional["ArticleRepositoryProtocol"] = None,
        health_repository: Optional["SourceHealthRepositoryProtocol"] = None,
    ):
        self.registry = SourceRegistry()
        self.bypass = BypassResolver()
        self.bus: PublicationBus = get_publication_bus()
        self.event_repository = event_repository
        self.article_repository = article_repository
        self.health_repository = health_repository
        self.swarm: Optional["ZombieSwarm"] = None
        self.canonical_runner: Optional["CanonicalPipelineRunner"] = None
        self._initialized = False
        self._subscribers: List[Callable[[Article], None]] = []

    def initialize(self, concurrency: int = 2) -> None:
        """Initialize the single unified feed pipeline."""
        if self._initialized:
            return

        # Start the application publication bus
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.bus.start())
        except RuntimeError:
            pass

        # --- Lazy imports to break circular dependency ---
        from ..zombies.swarm import ZombieSwarm
        from ..pipeline.runner import CanonicalPipelineRunner

        self.registry.load()

        # Initialize Canonical Pipeline Runner (Phase 3)
        self.canonical_runner = CanonicalPipelineRunner(
            bus=self.bus,
            event_repository=self.event_repository,
            article_repository=self.article_repository,
            max_concurrency=concurrency * 16,
        )

        # Initialize Zombie Swarm
        self.swarm = ZombieSwarm(
            self.registry,
            health_repository=self.health_repository,
        )
        self.swarm.set_ingestion_callback(self._on_zombie_found_source)

        self._initialized = True
        logger.info(f"UnifiedFeedChainEngine initialized successfully (Pipeline Mode: '{get_pipeline_mode()}').")

    async def _on_zombie_found_source(self, observation: Union[SourceObservation, Any]) -> None:
        """
        Callback fired by Zombies when they find a new item.
        Routes directly to Canonical Pipeline Runner.
        """
        mode = get_pipeline_mode()
        dry_run = (mode == "shadow")

        try:
            canonical_obs = observation
            if not isinstance(canonical_obs, SourceObservation):
                from ..pipeline.adapters import SourceObservationAdapter
                canonical_obs = SourceObservationAdapter.from_event_source(observation)

            if self.canonical_runner:
                res = await self.canonical_runner.process_observation(canonical_obs, dry_run=dry_run)
                if res.event and res.event.is_breaking:
                    logger.info(f"🚨 BREAKING EVENT DETECTED: {res.event.headline} - Triggering Feeding Frenzy!")
                    if self.swarm:
                        self.swarm.trigger_feeding_frenzy()
        except Exception as e:
            title = getattr(observation, "title", "unknown")
            logger.error(f"Canonical Pipeline failed to process observation '{title}': {e}", exc_info=True)

    async def start(self, concurrency: int = 1) -> None:
        """Start continuous background swarm loop."""
        if not self._initialized:
            self.initialize(concurrency=concurrency)
        if self.swarm:
            await self.swarm.start()

    def stop(self) -> None:
        """Stop background swarm loop and pipeline runners."""
        if self.swarm:
            self.swarm.stop()
        if self.canonical_runner:
            self.canonical_runner.stop()

    async def aclose(self) -> None:
        """Asynchronously stop all swarm workers, flush health state, and cleanup resources."""
        self.stop()
        if self.swarm:
            await self.swarm.aclose()
        if self.bus and self.bus.is_running:
            try:
                await self.bus.stop(drain_timeout=2.0)
            except Exception as e:
                logger.debug(f"PublicationBus stop error: {e}")
        self._initialized = False
        logger.info("UnifiedFeedChainEngine closed cleanly.")

    def subscribe(self, callback: Callable[[Article], None]) -> None:
        """Subscribe callback to receive articles as they clear the pipeline."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Article], None]) -> None:
        """Unsubscribe callback."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def get_articles(self, count: int = 1000) -> List[Article]:
        """Compatibility drain for legacy consumers."""
        return []


# Global singleton instance
unified_engine = UnifiedFeedChainEngine()

