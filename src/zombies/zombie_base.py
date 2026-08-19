"""
Zombie Base — Abstract base class for all Zombie species.

Defines the interface for specialized autonomous collectors.
Each zombie manages its own polling interval, adaptive hunger scoring,
and error recovery.
"""

from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, UTC
import logging
import random
from typing import Awaitable, Callable, List, Optional

from src.domain.enums import ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor

logger = logging.getLogger(__name__)

# Callback type for when a zombie discovers new observations
ObservationIngestionCallback = Callable[[SourceObservation], Awaitable[None]]


class ZombieBase(ABC):
    """Abstract base class for all specialized collectors in the Swarm."""
    
    species: ZombieSpecies

    def __init__(self, source: SourceDescriptor):
        self.source = source
        self.name = f"{self.species.value}[{source.name}]"
        
        # Adaptive polling parameters
        self.base_delay = source.delay_seconds
        self.min_delay = max(15.0, self.base_delay * 0.25)
        self.max_delay = max(300.0, self.base_delay * 5.0)
        
        # Hunger Score (0.0 to 1.0)
        # 1.0 = extremely hungry (polling very fast because of recent activity)
        # 0.0 = sated/dormant (polling slowly because source is quiet)
        self.hunger_score = 0.5
        
        self.is_running = False
        self._current_task: Optional[asyncio.Task] = None

    @abstractmethod
    async def hunt(self) -> List[SourceObservation]:
        """Discover new items from the source and normalize to canonical SourceObservations."""
        pass

    async def start_hunting(self, callback: Callable[[SourceObservation], Awaitable[None]]) -> None:
        """Start the autonomous hunting loop."""
        if self.is_running:
            return
        self.is_running = True
        
        logger.info(f"🧟 Zombie {self.name} started hunting.")
        
        while self.is_running:
            # Check cooldowns/blacklists
            now = datetime.now(UTC)
            if self.source.is_blacklisted:
                logger.warning(f"🧟 {self.name} dormant: source is blacklisted.")
                await asyncio.sleep(300)
                continue
                
            if self.source.cooldown_until and self.source.cooldown_until > now:
                sleep_sec = (self.source.cooldown_until - now).total_seconds()
                logger.debug(f"🧟 {self.name} resting for cooldown ({int(sleep_sec)}s)")
                await asyncio.sleep(min(sleep_sec, 60))
                continue

            try:
                # 1. Hunt
                new_sources = await self.hunt()
                
                # 2. Feed the Pipeline (call callback for each new observation)
                for observation in new_sources:
                    # Invariant: SourceObservation is a frozen dataclass; never mutate.
                    await callback(observation)
                
                # 3. Adapt hunger based on results
                self.adapt_hunger(len(new_sources) > 0, len(new_sources))
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"🧟 {self.name} encountered error during hunt: {e}")
                self.adapt_hunger(False, 0)
            
            # 4. Wait based on current hunger
            try:
                delay = self.calculate_current_delay()
                
                # Add a little jitter to avoid thundering herds
                jitter = delay * random.uniform(-0.1, 0.1)
                await asyncio.sleep(delay + jitter)
            except asyncio.CancelledError:
                break

    def stop_hunting(self) -> None:
        """Stop the hunting loop."""
        self.is_running = False
        logger.info(f"🧟 Zombie {self.name} stopped hunting.")

    async def aclose(self) -> None:
        """Asynchronous cleanup for network sessions and allocated resources."""
        self.stop_hunting()

    def adapt_hunger(self, found_new: bool, count: int) -> None:
        """Adapt the hunger score based on recent hunting success.
        
        If we found something new -> activity is high -> hunger increases (poll faster).
        If we found nothing -> source is quiet -> hunger decreases (poll slower).
        """
        if found_new:
            # Huge jump if we found multiple items, smaller jump if just one
            boost = 0.3 + (min(count, 5) * 0.05)
            self.hunger_score = min(1.0, self.hunger_score + boost)
        else:
            # Slowly decay hunger when nothing is found
            self.hunger_score = max(0.0, self.hunger_score - 0.1)
            
    def calculate_current_delay(self) -> float:
        """Calculate next polling delay based on hunger score.
        
        High hunger (1.0) -> min_delay
        Low hunger (0.0) -> max_delay
        """
        # Linear interpolation between max and min delay based on hunger
        return self.max_delay - (self.hunger_score * (self.max_delay - self.min_delay))

    def trigger_feeding_frenzy(self) -> None:
        """Force hunger to maximum (e.g. when an event is breaking elsewhere)."""
        self.hunger_score = 1.0
        logger.debug(f"🧟 {self.name} entered feeding frenzy!")
