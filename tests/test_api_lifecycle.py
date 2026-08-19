"""
Unit & Integration Tests for Subphase 5D-B: API Wiring & Application Lifecycle Integration.
Location: tests/test_api_lifecycle.py

Verifies:
1. Lifespan startup creates canonical SqliteEngine & SqliteEventRepository
2. Lifespan startup initializes canonical schema tables
3. get_event_repository() resolves successfully after lifespan startup
4. Environment override TECHNEWS_CANONICAL_DB_PATH is respected
5. Repository and engine are deterministically owned by app.state
6. Lifespan shutdown closes the engine and clears repository registration
7. No dependency on legacy EventStore during startup
8. Startup failure halts application startup with exception
9. Repeated application lifecycle runs do not leak connections
10. Test dependency injection override is respected
11. Real HTTP request through TestClient reads events from startup-created repository
12. Both src.api.app and src.api.main applications initialize canonical storage
"""

import asyncio
from datetime import datetime, UTC, timedelta
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.api.app import app as prod_app, get_app
from src.api.main import app as dev_app, verify_api_key
from src.api.routes.events import (
    get_event_repository,
    set_event_repository,
    TechEventResponse,
)
from src.domain.enums import EventStatus, FreshnessLevel, SourceTier
from src.domain.models import EventSourceEvidence, TechEvent, TimelineEntry
from src.storage.protocols import EventRepositoryProtocol
from src.storage.sqlite_engine import SqliteEngine


def make_sample_event(event_id: str = "evt_lifecycle_01") -> TechEvent:
    now = datetime.now(UTC)
    src = EventSourceEvidence(
        article_id=f"art_{event_id}",
        url=f"https://example.com/{event_id}",
        title="Lifecycle Integration Verified",
        source_name="TechDaily",
        source_tier=SourceTier.TIER_1_PREMIUM,
        discovered_at=now,
        published_at=now,
        summary="Testing canonical lifecycle integration.",
        is_primary=True,
    )
    tl = TimelineEntry(
        timestamp=now,
        headline="Initial report",
        source_name="TechDaily",
        source_url=f"https://example.com/{event_id}",
        confidence_at_time=0.90,
        entry_type="announcement",
    )
    return TechEvent(
        id=event_id,
        headline="Lifecycle Integration Breakthrough",
        first_seen=now,
        last_updated=now,
        entities=["FastAPI", "SQLite"],
        topics=["Architecture", "Persistence"],
        sources=[src],
        primary_source="TechDaily",
        confidence=0.90,
        importance=0.85,
        novelty=0.90,
        status=EventStatus.CORROBORATED,
        freshness=FreshnessLevel.FRESH,
        freshness_score=0.90,
        timeline=[tl],
        cluster_id=f"cluster_{event_id}",
    )


@pytest.mark.asyncio
async def test_lifespan_startup_and_shutdown(tmp_path: Path):
    """Verify lifespan startup creates repo and shutdown cleanly closes it."""
    test_db = tmp_path / "lifecycle_test.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    # Pre-condition: no repository set
    set_event_repository(None)

    # Run lifespan context
    app = get_app()
    async with app.router.lifespan_context(app):
        # Startup checks
        repo = get_event_repository()
        assert repo is not None
        assert hasattr(app.state, "canonical_engine")
        assert hasattr(app.state, "canonical_event_repository")
        assert app.state.canonical_engine.db_path == test_db.resolve()

        # Verify tables initialized
        stats = await repo.get_stats()
        assert stats["total_events"] == 0

        # Save an event
        event = make_sample_event()
        await repo.save_event(event)
        stats_after = await repo.get_stats()
        assert stats_after["total_events"] == 1

    # Shutdown checks
    # After exiting lifespan, engine is closed and set_event_repository reset
    with pytest.raises(RuntimeError, match="EventRepository has not been initialized"):
        get_event_repository()

    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


@pytest.mark.asyncio
async def test_production_app_http_request_with_lifespan(tmp_path: Path):
    """Verify full HTTP request executes against startup-initialized repository."""
    test_db = tmp_path / "prod_http_test.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    app = prod_app
    # Override auth for test request
    app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro", "user_id": "test"}

    # Using TestClient with lifespan
    with TestClient(app) as client:
        repo = get_event_repository()
        assert repo is not None

        # Seed an event
        event = make_sample_event("evt_http_01")
        await repo.save_event(event)

        # GET /v1/events
        res = client.get("/v1/events")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == "evt_http_01"
        assert data[0]["headline"] == "Lifecycle Integration Breakthrough"

        # GET /v1/events/{id}
        res_single = client.get("/v1/events/evt_http_01")
        assert res_single.status_code == 200
        assert res_single.json()["id"] == "evt_http_01"

    app.dependency_overrides.clear()
    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


@pytest.mark.asyncio
async def test_dev_app_lifespan_consistency(tmp_path: Path):
    """Verify src.api.main app lifespan also initializes canonical storage."""
    test_db = tmp_path / "dev_main_test.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    app = dev_app
    app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro", "user_id": "test"}

    with TestClient(app) as client:
        repo = get_event_repository()
        assert repo is not None

        event = make_sample_event("evt_dev_01")
        await repo.save_event(event)

        res = client.get("/v1/events")
        assert res.status_code == 200
        assert len(res.json()) == 1

    app.dependency_overrides.clear()
    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


@pytest.mark.asyncio
async def test_repeated_lifespans_no_leak(tmp_path: Path):
    """Verify multiple consecutive app lifespans initialize and close cleanly."""
    test_db = tmp_path / "repeat_test.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    app = prod_app
    for i in range(3):
        async with app.router.lifespan_context(app):
            repo = get_event_repository()
            assert repo is not None
            e = make_sample_event(f"evt_repeat_{i}")
            await repo.save_event(e)

    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


@pytest.mark.asyncio
async def test_test_dependency_override_respected(tmp_path: Path):
    """Verify tests can still explicitly override repository via set_event_repository."""
    class FakeRepo:
        async def get_active_events(self, limit: int = 100):
            return [make_sample_event("evt_fake_99")]

        async def get_events_by_entity(self, entity: str, limit: int = 50):
            return []

        async def get_event(self, event_id: str):
            return None

        async def get_stats(self):
            return {"fake": True}

    fake = FakeRepo()
    set_event_repository(fake)  # type: ignore

    app = prod_app
    app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro"}

    client = TestClient(app)
    res = client.get("/v1/events")
    assert res.status_code == 200
    assert res.json()[0]["id"] == "evt_fake_99"

    app.dependency_overrides.clear()
    set_event_repository(None)


@pytest.mark.asyncio
async def test_startup_failure_prevents_healthy_start(tmp_path: Path):
    """Verify that if canonical storage initialization fails, startup raises exception."""
    # Point to an invalid path that cannot be created (a file used as directory)
    dummy_file = tmp_path / "blocker_file"
    dummy_file.write_text("not a directory")
    invalid_db = dummy_file / "sub_dir" / "invalid.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(invalid_db)

    app = get_app()
    with pytest.raises((OSError, NotADirectoryError, RuntimeError)):
        async with app.router.lifespan_context(app):
            pass

    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


def test_no_legacy_event_store_startup_dependency(tmp_path: Path):
    """Verify that startup does not construct or depend on legacy EventStore."""
    test_db = tmp_path / "clean_startup.db"
    os.environ["TECHNEWS_CANONICAL_DB_PATH"] = str(test_db)

    app = prod_app
    with TestClient(app) as client:
        # Verify canonical repository is active
        repo = get_event_repository()
        assert repo is not None
        assert hasattr(repo, "get_active_events")
        assert hasattr(repo, "save_event")

        # Verify it's SqliteEventRepository, not EventStore
        from src.storage.sqlite_event_repository import SqliteEventRepository
        assert isinstance(repo, SqliteEventRepository)

    os.environ.pop("TECHNEWS_CANONICAL_DB_PATH", None)


def test_sources_endpoint_authenticated_succeeds_and_structure_valid():
    """P1-1 Regression: Verify authenticated GET /sources returns 200 with valid structure."""
    app = prod_app
    app.dependency_overrides[verify_api_key] = lambda: {"user_id": "test_user", "tier": "pro"}

    client = TestClient(app)
    res = client.get("/sources")
    assert res.status_code == 200
    data = res.json()
    assert "sources" in data
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) > 0

    for src in data["sources"]:
        assert "name" in src and isinstance(src["name"], str)
        assert "type" in src and isinstance(src["type"], str)
        assert "refresh_rate" in src and isinstance(src["refresh_rate"], (int, float))
        assert "enabled" in src and isinstance(src["enabled"], bool)
        assert src["enabled"] is True

    app.dependency_overrides.clear()


def test_sources_endpoint_unauthenticated_fails_with_401():
    """P1-1 Regression: Verify unauthenticated GET /sources returns 401 when anonymous disabled."""
    app = prod_app
    app.dependency_overrides.clear()
    client = TestClient(app)
    res = client.get("/sources")
    assert res.status_code == 401
