"""
Unit Tests for ZombieBase Abstract Base Class.
Location: tests/test_zombie_base.py

Tests:
  - Lifecycle: start_hunting, stop_hunting, and is_running flags
  - Hunting callback: ensures canonical SourceObservation is dispatched
  - Immutable SourceObservation handling: frozen dataclass invariant
  - Hunger adaptation: boost on discovery, decay on empty
  - Delay calculation & jitter: min_delay, max_delay, interpolation
  - Error resilience: handles exceptions in hunt() gracefully
  - Cooldown & blacklist: pauses when blacklisted or cooled down
  - Feeding frenzy: hunger forced to 1.0
  - Async cleanup: aclose() closes gracefully
"""

import asyncio
from datetime import datetime, UTC, timedelta
from typing import List
from unittest.mock import AsyncMock, patch
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.source_registry import SourceDescriptor, SourceType
from src.zombies.zombie_base import ZombieBase


class DummyZombie(ZombieBase):
    """Concrete test implementation of ZombieBase."""
    species = ZombieSpecies.RSS

    def __init__(self, source: SourceDescriptor, mock_observations: List[SourceObservation] = None):
        super().__init__(source)
        self.mock_observations = mock_observations or []
        self.hunt_call_count = 0
        self.raise_in_hunt = False

    async def hunt(self) -> List[SourceObservation]:
        self.hunt_call_count += 1
        if self.raise_in_hunt:
            raise RuntimeError("Mock network error during hunt")
        return self.mock_observations


@pytest.fixture
def sample_source_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="test_rss_src",
        url="https://example.com/rss",
        name="Example RSS",
        type=SourceType.RSS,
        tier=1,
        delay_seconds=20.0,
    )


@pytest.fixture
def sample_observation() -> SourceObservation:
    return SourceObservation.create(
        source_id="test_rss_src",
        source_name="Example RSS",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://example.com/article-1",
        title="Breaking Tech Discovery",
        summary="A major breakthrough in AI computing.",
        published_at_hint=datetime.now(UTC),
    )


# =============================================================================
# 1. INITIALIZATION & DELAY CALCULATION TESTS
# =============================================================================

def test_zombie_initialization(sample_source_descriptor):
    zombie = DummyZombie(sample_source_descriptor)
    assert zombie.source == sample_source_descriptor
    assert zombie.species == ZombieSpecies.RSS
    assert zombie.name == "z_rss[Example RSS]"
    assert zombie.base_delay == 20.0
    assert zombie.min_delay == 15.0  # max(15.0, 20.0 * 0.25) = 15.0
    assert zombie.max_delay == 300.0  # max(300.0, 20.0 * 5.0) = 300.0
    assert zombie.hunger_score == 0.5
    assert zombie.is_running is False


def test_delay_calculation_boundaries(sample_source_descriptor):
    zombie = DummyZombie(sample_source_descriptor)
    
    # 0.0 hunger -> max_delay
    zombie.hunger_score = 0.0
    assert zombie.calculate_current_delay() == zombie.max_delay

    # 1.0 hunger -> min_delay
    zombie.hunger_score = 1.0
    assert zombie.calculate_current_delay() == zombie.min_delay

    # 0.5 hunger -> midpoint
    zombie.hunger_score = 0.5
    expected_midpoint = zombie.max_delay - 0.5 * (zombie.max_delay - zombie.min_delay)
    assert zombie.calculate_current_delay() == pytest.approx(expected_midpoint)


# =============================================================================
# 2. HUNGER ADAPTATION & FEEDING FRENZY TESTS
# =============================================================================

def test_hunger_adaptation_boost_and_decay(sample_source_descriptor):
    zombie = DummyZombie(sample_source_descriptor)
    zombie.hunger_score = 0.4

    # Discovered 1 item: boost = 0.3 + min(1, 5)*0.05 = 0.35
    zombie.adapt_hunger(found_new=True, count=1)
    assert zombie.hunger_score == pytest.approx(0.75)

    # Discovered multiple items (capped at 1.0)
    zombie.adapt_hunger(found_new=True, count=10)
    assert zombie.hunger_score == 1.0

    # No items discovered: decay by 0.1
    zombie.adapt_hunger(found_new=False, count=0)
    assert zombie.hunger_score == pytest.approx(0.9)

    # Decay all the way to 0.0
    for _ in range(15):
        zombie.adapt_hunger(found_new=False, count=0)
    assert zombie.hunger_score == 0.0


def test_trigger_feeding_frenzy(sample_source_descriptor):
    zombie = DummyZombie(sample_source_descriptor)
    zombie.hunger_score = 0.1
    zombie.trigger_feeding_frenzy()
    assert zombie.hunger_score == 1.0
    assert zombie.calculate_current_delay() == zombie.min_delay


# =============================================================================
# 3. HUNTING LIFECYCLE & CALLBACK DISPATCH TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_start_hunting_dispatches_canonical_observations(sample_source_descriptor, sample_observation):
    zombie = DummyZombie(sample_source_descriptor, mock_observations=[sample_observation])
    received_observations: List[SourceObservation] = []

    async def mock_callback(obs: SourceObservation) -> None:
        received_observations.append(obs)
        # Stop zombie after receiving first observation to avoid infinite loop
        zombie.stop_hunting()

    # Fast-forward sleep
    with patch("asyncio.sleep", AsyncMock()):
        await zombie.start_hunting(mock_callback)

    assert zombie.hunt_call_count >= 1
    assert len(received_observations) == 1
    assert received_observations[0] == sample_observation
    assert received_observations[0].zombie_species == ZombieSpecies.RSS
    assert zombie.is_running is False


@pytest.mark.asyncio
async def test_immutable_source_observation_invariant(sample_source_descriptor, sample_observation):
    zombie = DummyZombie(sample_source_descriptor, mock_observations=[sample_observation])

    async def mock_callback(obs: SourceObservation) -> None:
        # Verify that SourceObservation is immutable
        with pytest.raises(Exception):
            obs.title = "Mutated Title"
        with pytest.raises(Exception):
            obs.zombie_species = ZombieSpecies.WEB
        zombie.stop_hunting()

    with patch("asyncio.sleep", AsyncMock()):
        await zombie.start_hunting(mock_callback)


@pytest.mark.asyncio
async def test_error_resilience_during_hunt(sample_source_descriptor):
    zombie = DummyZombie(sample_source_descriptor)
    zombie.raise_in_hunt = True
    zombie.hunger_score = 0.8

    call_count = 0

    async def mock_callback(obs: SourceObservation) -> None:
        pass

    async def mock_sleep(delay: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            zombie.stop_hunting()

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await zombie.start_hunting(mock_callback)

    assert zombie.hunt_call_count >= 2
    # Hunger should have decayed after errors
    assert zombie.hunger_score < 0.8


@pytest.mark.asyncio
async def test_blacklist_dormancy(sample_source_descriptor):
    sample_source_descriptor.is_blacklisted = True
    zombie = DummyZombie(sample_source_descriptor)

    sleep_calls = []

    async def mock_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        zombie.stop_hunting()

    async def mock_callback(obs: SourceObservation) -> None:
        pass

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await zombie.start_hunting(mock_callback)

    assert zombie.hunt_call_count == 0  # Did not hunt because blacklisted
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 300


@pytest.mark.asyncio
async def test_cooldown_dormancy(sample_source_descriptor):
    now = datetime.now(UTC)
    sample_source_descriptor.cooldown_until = now + timedelta(seconds=45)
    zombie = DummyZombie(sample_source_descriptor)

    sleep_calls = []

    async def mock_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        zombie.stop_hunting()

    async def mock_callback(obs: SourceObservation) -> None:
        pass

    with patch("asyncio.sleep", side_effect=mock_sleep):
        await zombie.start_hunting(mock_callback)

    assert zombie.hunt_call_count == 0  # Did not hunt because cooled down
    assert len(sleep_calls) == 1
    assert 0 < sleep_calls[0] <= 60


@pytest.mark.asyncio
async def test_async_close_cleanup(sample_source_descriptor):
    zombie = DummyZombie(sample_source_descriptor)
    zombie.is_running = True
    await zombie.aclose()
    assert zombie.is_running is False
