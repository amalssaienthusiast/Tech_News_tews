"""
Unit Tests for ZombieSwarm and UnifiedFeedChainEngine Ingestion Integration.
Location: tests/test_zombie_swarm.py

Tests:
  - ZombieSwarm initialization and species routing (RSS, Web, Corp, Security, GitHub, Hacker News)
  - Canonical SourceObservation callback registration & dispatch
  - Direct UnifiedFeedChainEngine._on_zombie_found_source integration without SourceObservationAdapter
  - Feeding frenzy URL matching (exact domain, subdomain, netloc parsing)
  - Malformed URL resilience in feeding frenzy (no IndexError / crashes)
  - Swarm lifecycle management: start(), stop(), aclose(), task tracking
  - Exception isolation: failing zombie does not crash swarm or pipeline runner
  - Architecture boundaries & frozen model invariance
"""

import asyncio
from datetime import datetime, UTC
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.engine.publication_bus import PublicationBus
from src.engine.source_registry import SourceDescriptor, SourceRegistry, SourceType
from src.engine.unified_chain import UnifiedFeedChainEngine
from src.zombies.swarm import ZombieSwarm
from src.zombies.z_corp import ZCorp
from src.zombies.z_github import ZGitHub
from src.zombies.z_hacker import ZHacker
from src.zombies.z_rss import ZRss
from src.zombies.z_security import ZSecurity
from src.zombies.z_web import ZWeb


@pytest.fixture
def mock_registry() -> SourceRegistry:
    registry = SourceRegistry()
    registry._sources = {
        "rss_tech": SourceDescriptor(id="rss_tech", url="https://technews.example.com/rss", name="Tech News RSS", type=SourceType.RSS, tier=1),
        "web_tech": SourceDescriptor(id="web_tech", url="https://techsite.example.com", name="Tech Site Web", type=SourceType.HTML, tier=3),
        "corp_blog": SourceDescriptor(id="corp_blog", url="https://openai.com/blog/rss", name="OpenAI Blog", type=SourceType.RSS, tier=1),
        "sec_feed": SourceDescriptor(id="sec_feed", url="https://cisa.gov/advisories/cve.xml", name="CISA Security Feed", type=SourceType.RSS, tier=1),
    }
    return registry


@pytest.fixture
def sample_observation() -> SourceObservation:
    return SourceObservation.create(
        source_id="rss_tech",
        source_name="Tech News RSS",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://technews.example.com/item-100",
        title="Major Semiconductor Announcement",
        raw_content="",
        summary="A major announcement regarding next-gen silicon.",
        published_at_hint=datetime.now(UTC),
    )


# =============================================================================
# 1. SWARM INITIALIZATION & SPECIES ROUTING TESTS
# =============================================================================

def test_swarm_species_routing(mock_registry):
    swarm = ZombieSwarm(mock_registry)
    
    # Verify factory routing
    rss_zombie = swarm._create_zombie_for_source(mock_registry.get_source("rss_tech"))
    assert isinstance(rss_zombie, ZRss)
    assert rss_zombie.species == ZombieSpecies.RSS

    web_zombie = swarm._create_zombie_for_source(mock_registry.get_source("web_tech"))
    assert isinstance(web_zombie, ZWeb)
    assert web_zombie.species == ZombieSpecies.WEB

    corp_zombie = swarm._create_zombie_for_source(mock_registry.get_source("corp_blog"))
    assert isinstance(corp_zombie, ZCorp)
    assert corp_zombie.species == ZombieSpecies.CORPORATE

    sec_zombie = swarm._create_zombie_for_source(mock_registry.get_source("sec_feed"))
    assert isinstance(sec_zombie, ZSecurity)
    assert sec_zombie.species == ZombieSpecies.SECURITY


@pytest.mark.asyncio
async def test_swarm_start_spawns_all_species_and_specialized_zombies(mock_registry):
    swarm = ZombieSwarm(mock_registry)
    dispatched_observations: List[SourceObservation] = []

    async def mock_callback(obs: SourceObservation) -> None:
        dispatched_observations.append(obs)

    swarm.set_ingestion_callback(mock_callback)

    # Mock start_hunting on all zombies so they don't loop forever
    with patch.object(ZRss, "start_hunting", AsyncMock()), \
         patch.object(ZWeb, "start_hunting", AsyncMock()), \
         patch.object(ZCorp, "start_hunting", AsyncMock()), \
         patch.object(ZSecurity, "start_hunting", AsyncMock()), \
         patch.object(ZGitHub, "start_hunting", AsyncMock()), \
         patch.object(ZHacker, "start_hunting", AsyncMock()):
        await swarm.start()

    # 4 registry sources + 2 specialized API zombies (gh_api, hn_api) = 6 total
    assert len(swarm._zombies) == 6
    assert "gh_api" in swarm._zombies
    assert "hn_api" in swarm._zombies
    assert isinstance(swarm._zombies["gh_api"], ZGitHub)
    assert isinstance(swarm._zombies["hn_api"], ZHacker)
    assert len(swarm._tasks) == 6
    assert swarm._is_running is True

    # Stop swarm
    swarm.stop()
    assert swarm._is_running is False
    assert len(swarm._tasks) == 0


# =============================================================================
# 2. FEEDING FRENZY URL PARSING TESTS
# =============================================================================

def test_feeding_frenzy_domain_matching(mock_registry):
    swarm = ZombieSwarm(mock_registry)
    
    # Manually populate zombies for testing
    rss_zombie = ZRss(mock_registry.get_source("rss_tech"))
    corp_zombie = ZCorp(mock_registry.get_source("corp_blog"))
    swarm._zombies["rss_tech"] = rss_zombie
    swarm._zombies["corp_blog"] = corp_zombie

    rss_zombie.trigger_feeding_frenzy = MagicMock()
    corp_zombie.trigger_feeding_frenzy = MagicMock()

    # Trigger with OpenAI URL -> should only trigger corp_blog
    swarm.trigger_feeding_frenzy("https://openai.com/blog/new-model-release")
    corp_zombie.trigger_feeding_frenzy.assert_called_once()
    rss_zombie.trigger_feeding_frenzy.assert_not_called()


def test_feeding_frenzy_malformed_url_safety(mock_registry):
    swarm = ZombieSwarm(mock_registry)
    rss_zombie = ZRss(mock_registry.get_source("rss_tech"))
    swarm._zombies["rss_tech"] = rss_zombie
    rss_zombie.trigger_feeding_frenzy = MagicMock()

    # Malformed URLs that would crash split('/')[2]
    malformed_inputs = [
        "not-a-url",
        "://invalid",
        "http:",
        "",
        "/////",
        "https://",
    ]

    for malformed in malformed_inputs:
        # Must not raise IndexError or ValueError
        swarm.trigger_feeding_frenzy(malformed)


def test_feeding_frenzy_global_broadcast(mock_registry):
    swarm = ZombieSwarm(mock_registry)
    rss_zombie = ZRss(mock_registry.get_source("rss_tech"))
    corp_zombie = ZCorp(mock_registry.get_source("corp_blog"))
    swarm._zombies["rss_tech"] = rss_zombie
    swarm._zombies["corp_blog"] = corp_zombie

    rss_zombie.trigger_feeding_frenzy = MagicMock()
    corp_zombie.trigger_feeding_frenzy = MagicMock()

    # None source_url triggers all zombies
    swarm.trigger_feeding_frenzy(None)
    rss_zombie.trigger_feeding_frenzy.assert_called_once()
    corp_zombie.trigger_feeding_frenzy.assert_called_once()


# =============================================================================
# 3. DIRECT UNIFIED FEED CHAIN INGESTION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_direct_pipeline_ingestion_without_adapter(sample_observation):
    engine = UnifiedFeedChainEngine()
    engine.bus = PublicationBus()
    
    mock_runner = MagicMock()
    mock_pipeline_result = MagicMock()
    mock_pipeline_result.event = None
    mock_runner.process_observation = AsyncMock(return_value=mock_pipeline_result)
    engine.canonical_runner = mock_runner

    # Verify that SourceObservationAdapter is NEVER called in _on_zombie_found_source
    with patch("src.pipeline.adapters.SourceObservationAdapter.from_event_source") as mock_adapter:
        await engine._on_zombie_found_source(sample_observation)
        mock_adapter.assert_not_called()

    # Direct canonical runner invocation
    mock_runner.process_observation.assert_awaited_once_with(sample_observation, dry_run=False)


@pytest.mark.asyncio
async def test_engine_trigger_frenzy_on_breaking_event(sample_observation):
    engine = UnifiedFeedChainEngine()
    engine.bus = PublicationBus()
    
    mock_event = MagicMock()
    mock_event.is_breaking = True
    mock_event.headline = "Quantum Breakthrough Detected"

    mock_pipeline_result = MagicMock()
    mock_pipeline_result.event = mock_event
    
    mock_runner = MagicMock()
    mock_runner.process_observation = AsyncMock(return_value=mock_pipeline_result)
    engine.canonical_runner = mock_runner

    mock_swarm = MagicMock()
    engine.swarm = mock_swarm

    await engine._on_zombie_found_source(sample_observation)
    mock_swarm.trigger_feeding_frenzy.assert_called_once()


# =============================================================================
# 4. LIFECYCLE, ASYNC CLEANUP & EXCEPTION ISOLATION
# =============================================================================

@pytest.mark.asyncio
async def test_swarm_aclose_cleans_all_zombies(mock_registry):
    swarm = ZombieSwarm(mock_registry)
    swarm.set_ingestion_callback(AsyncMock())

    with patch.object(ZRss, "start_hunting", AsyncMock()), \
         patch.object(ZWeb, "start_hunting", AsyncMock()), \
         patch.object(ZCorp, "start_hunting", AsyncMock()), \
         patch.object(ZSecurity, "start_hunting", AsyncMock()), \
         patch.object(ZGitHub, "start_hunting", AsyncMock()), \
         patch.object(ZHacker, "start_hunting", AsyncMock()):
        await swarm.start()

    assert swarm._is_running is True
    await swarm.aclose()
    assert swarm._is_running is False
    assert len(swarm._zombies) == 0


@pytest.mark.asyncio
async def test_exception_isolation_in_engine_callback(sample_observation):
    engine = UnifiedFeedChainEngine()
    engine.bus = PublicationBus()
    
    mock_runner = MagicMock()
    mock_runner.process_observation = AsyncMock(side_effect=RuntimeError("Pipeline internal processing error"))
    engine.canonical_runner = mock_runner

    # Must catch and log error without bubbling or crashing engine loop
    await engine._on_zombie_found_source(sample_observation)
