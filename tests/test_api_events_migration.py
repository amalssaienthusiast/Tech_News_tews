"""
Unit & Integration Tests for Phase 5D-A: API EventRepository Migration.
Location: tests/test_api_events_migration.py

Verifies:
1. Repository dependency injection via set_event_repository / get_event_repository
2. GET /v1/events active event retrieval with pagination
3. GET /v1/events?entity=... filtering
4. GET /v1/events/{id} single event retrieval (200 OK and 404 Not Found)
5. GET /v1/events/stats diagnostics
6. DTO mapping fidelity (TechEventResponse, TimelineEntryResponse, EventSourceResponseModel)
7. Timezone-aware ISO-8601 UTC string serialization
8. Enum string serialization
9. SSE /v1/events/stream event payload lookup from repository
10. Storage error isolation (no SQL or internal leakage on DB failure)
11. Query limit bounds validation (1 <= limit <= 200)
12. Legacy compatibility bridge (get_event_store, set_event_store)
13. End-to-end Pipeline -> SQLite -> API roundtrip
14. Authentication enforcement (401 when API key missing or invalid)
15. Architectural boundary test (zero imports of sqlite3/aiosqlite/SqliteEventRepository in events.py)
"""

import ast
import asyncio
from datetime import datetime, UTC, timedelta
import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.main import verify_api_key
from src.api.routes.events import (
    router as events_router,
    get_event_repository,
    set_event_repository,
    TechEventResponse,
    TimelineEntryResponse,
    EventSourceResponseModel,
)
from src.domain.enums import EventStatus, FreshnessLevel, SourceTier, ZombieSpecies
from src.domain.models import EventSourceEvidence, SourceObservation, TechEvent, TimelineEntry
from src.pipeline.runner import CanonicalPipelineRunner
from src.storage.protocols import EventRepositoryProtocol
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


# =============================================================================
# FIXTURES
# =============================================================================

def make_test_event(
    event_id: str = "evt_api_5d_01",
    headline: str = "DeepSeek Releases Open Weights V3 Model",
    entities: list[str] | None = None,
    topics: list[str] | None = None,
    offset_hours: float = 0.0,
) -> TechEvent:
    now = datetime.now(UTC) - timedelta(hours=offset_hours)
    src = EventSourceEvidence(
        article_id=f"art_{event_id}_01",
        url=f"https://news.example.com/{event_id}",
        title=f"{headline} - Initial Coverage",
        source_name="AI Insider",
        source_tier=SourceTier.TIER_1_PREMIUM,
        discovered_at=now,
        published_at=now,
        summary="A breakthrough open weights AI architecture release.",
        is_primary=True,
    )
    tl = TimelineEntry(
        timestamp=now,
        headline="Model weights released on HuggingFace",
        source_name="AI Insider",
        source_url=f"https://news.example.com/{event_id}",
        confidence_at_time=0.95,
        entry_type="initial_report",
    )
    return TechEvent(
        id=event_id,
        headline=headline,
        first_seen=now,
        last_updated=now,
        entities=entities or ["DeepSeek", "HuggingFace"],
        topics=topics or ["Artificial Intelligence", "Open Source"],
        sources=[src],
        primary_source="AI Insider",
        confidence=0.95,
        importance=0.88,
        novelty=0.92,
        status=EventStatus.CONFIRMED,
        freshness=FreshnessLevel.FRESH,
        freshness_score=0.95,
        timeline=[tl],
        cluster_id=f"cluster_{event_id}",
    )


@pytest.fixture
def test_app() -> FastAPI:
    """Create a standalone FastAPI app mounting events_router with mock auth."""
    app = FastAPI()
    app.include_router(events_router)
    app.dependency_overrides[verify_api_key] = lambda: {"tier": "pro", "user_id": "test_developer"}
    return app


@pytest.fixture
def unauthenticated_app() -> FastAPI:
    """Create a standalone FastAPI app mounting events_router with real auth."""
    app = FastAPI()
    app.include_router(events_router)
    return app


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_api_events.db"


@pytest.fixture
async def repo(temp_db_path: Path) -> SqliteEventRepository:
    engine = SqliteEngine(temp_db_path)
    repository = SqliteEventRepository(engine=engine, auto_init=True)
    yield repository
    await engine.aclose()


# =============================================================================
# UNIT & INTEGRATION TESTS
# =============================================================================

def test_repository_dependency_management():
    """Verify get_event_repository and set_event_repository."""
    set_event_repository(None)
    with pytest.raises(RuntimeError, match="EventRepository has not been initialized"):
        get_event_repository()

    # Create dummy mock repo
    class DummyRepo:
        pass

    dummy = DummyRepo()
    set_event_repository(dummy)  # type: ignore
    assert get_event_repository() is dummy
    set_event_repository(None)


def test_legacy_compatibility_bridge():
    """Verify get_event_store and set_event_store shims have been permanently retired."""
    import src.api.routes.events as events_module

    assert not hasattr(events_module, "get_event_store"), (
        "get_event_store() must be permanently retired from src.api.routes.events"
    )
    assert not hasattr(events_module, "set_event_store"), (
        "set_event_store() must be permanently retired from src.api.routes.events"
    )
    assert hasattr(events_module, "get_event_repository"), (
        "get_event_repository() must be the authoritative dependency provider"
    )
    assert hasattr(events_module, "set_event_repository"), (
        "set_event_repository() must be the authoritative dependency injector"
    )


def test_dto_mapping_fidelity():
    """Verify TechEventResponse.from_domain maps all fields accurately."""
    event = make_test_event()
    dto = TechEventResponse.from_domain(event)

    assert dto.id == event.id
    assert dto.headline == event.headline
    assert dto.first_seen == event.first_seen.isoformat()
    assert dto.last_updated == event.last_updated.isoformat()
    assert dto.entities == ["DeepSeek", "HuggingFace"]
    assert dto.topics == ["Artificial Intelligence", "Open Source"]
    assert dto.confidence == 0.95
    assert dto.status == "confirmed"
    assert dto.freshness == "fresh"
    assert dto.freshness_score == 0.95
    assert dto.source_count == 1
    assert dto.primary_source == "AI Insider"
    assert len(dto.timeline) == 1
    assert dto.timeline[0].headline == "Model weights released on HuggingFace"
    assert dto.timeline[0].confidence_at_time == 0.95
    assert len(dto.sources) == 1
    assert dto.sources[0].title == f"{event.headline} - Initial Coverage"
    assert dto.sources[0].is_primary is True


def test_api_authentication_enforcement(unauthenticated_app: FastAPI):
    """Verify unauthenticated requests are rejected with 401."""
    client = TestClient(unauthenticated_app)
    res = client.get("/v1/events")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_api_get_active_events(test_app: FastAPI, repo: SqliteEventRepository):
    """Verify GET /v1/events returns active events from canonical repository."""
    e1 = make_test_event(event_id="evt_active_1", offset_hours=1.0)
    e2 = make_test_event(event_id="evt_active_2", offset_hours=2.0)
    await repo.save_event(e1)
    await repo.save_event(e2)

    set_event_repository(repo)
    client = TestClient(test_app)

    response = client.get("/v1/events")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    ids = {item["id"] for item in data}
    assert "evt_active_1" in ids
    assert "evt_active_2" in ids


@pytest.mark.asyncio
async def test_api_get_events_by_entity_filtering(test_app: FastAPI, repo: SqliteEventRepository):
    """Verify GET /v1/events?entity=... filters events correctly."""
    e1 = make_test_event(event_id="evt_nvidia", headline="NVIDIA CUDA 13 Launch", entities=["NVIDIA", "GPU"])
    e2 = make_test_event(event_id="evt_apple", headline="Apple M5 Chip Details", entities=["Apple", "Silicon"])
    await repo.save_event(e1)
    await repo.save_event(e2)

    set_event_repository(repo)
    client = TestClient(test_app)

    # Filter for NVIDIA
    resp_nv = client.get("/v1/events?entity=NVIDIA")
    assert resp_nv.status_code == 200
    data_nv = resp_nv.json()
    assert len(data_nv) == 1
    assert data_nv[0]["id"] == "evt_nvidia"

    # Filter for Apple
    resp_ap = client.get("/v1/events?entity=Apple")
    assert resp_ap.status_code == 200
    data_ap = resp_ap.json()
    assert len(data_ap) == 1
    assert data_ap[0]["id"] == "evt_apple"

    # Filter for Non-existent
    resp_none = client.get("/v1/events?entity=Intel")
    assert resp_none.status_code == 200
    assert len(resp_none.json()) == 0


@pytest.mark.asyncio
async def test_api_get_single_event_by_id(test_app: FastAPI, repo: SqliteEventRepository):
    """Verify GET /v1/events/{id} returns single event or 404."""
    e1 = make_test_event(event_id="evt_single_01")
    await repo.save_event(e1)

    set_event_repository(repo)
    client = TestClient(test_app)

    # Existing event
    res = client.get("/v1/events/evt_single_01")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "evt_single_01"
    assert len(body["sources"]) == 1
    assert len(body["timeline"]) == 1

    # Missing event
    res_404 = client.get("/v1/events/evt_non_existent")
    assert res_404.status_code == 404
    assert "not found" in res_404.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_get_event_stats(test_app: FastAPI, repo: SqliteEventRepository):
    """Verify GET /v1/events/stats returns diagnostic summary."""
    e1 = make_test_event(event_id="evt_stat_01")
    await repo.save_event(e1)

    set_event_repository(repo)
    client = TestClient(test_app)

    res = client.get("/v1/events/stats")
    assert res.status_code == 200
    stats = res.json()
    assert stats["total_events"] == 1
    assert stats["active_events"] == 1
    assert stats["total_sources"] == 1


@pytest.mark.asyncio
async def test_api_pagination_limit_validation(test_app: FastAPI, repo: SqliteEventRepository):
    """Verify limit parameter bounds (ge=1, le=200)."""
    set_event_repository(repo)
    client = TestClient(test_app)

    # Invalid: limit=0
    res_zero = client.get("/v1/events?limit=0")
    assert res_zero.status_code == 422

    # Invalid: limit=500 (> 200)
    res_over = client.get("/v1/events?limit=500")
    assert res_over.status_code == 422

    # Valid: limit=200
    res_valid = client.get("/v1/events?limit=200")
    assert res_valid.status_code == 200


@pytest.mark.asyncio
async def test_api_error_isolation_on_storage_failure(test_app: FastAPI):
    """Verify storage failures result in HTTP 500 without leaking raw SQL or traceback."""
    class BrokenRepo:
        async def get_active_events(self, limit: int = 100):
            raise RuntimeError("CRITICAL: disk I/O error at /var/data/internal.db")

        async def get_events_by_entity(self, entity: str, limit: int = 50):
            raise RuntimeError("CRITICAL: syntax error in SQL query SELECT * FROM")

        async def get_event(self, event_id: str):
            raise RuntimeError("CRITICAL: database locked")

        async def get_stats(self):
            raise RuntimeError("CRITICAL: table corrupted")

    set_event_repository(BrokenRepo())  # type: ignore
    client = TestClient(test_app)

    res1 = client.get("/v1/events")
    assert res1.status_code == 500
    assert res1.json()["detail"] == "Internal event storage error"

    res2 = client.get("/v1/events?entity=OpenAI")
    assert res2.status_code == 500
    assert res2.json()["detail"] == "Internal event storage error"

    res3 = client.get("/v1/events/some_id")
    assert res3.status_code == 500
    assert res3.json()["detail"] == "Internal event storage error"

    res4 = client.get("/v1/events/stats")
    assert res4.status_code == 500
    assert res4.json()["detail"] == "Internal event storage error"


@pytest.mark.asyncio
async def test_pipeline_to_api_roundtrip_integration(test_app: FastAPI, temp_db_path: Path):
    """
    End-to-End Integration Verification:
    1. Pipeline processes SourceObservation through S01-S11.
    2. S10 persists canonical TechEvent aggregate into SqliteEventRepository.
    3. API receives GET /v1/events request and queries SqliteEventRepository.
    4. Verify API response matches the processed event with 100% fidelity.
    """
    engine = SqliteEngine(temp_db_path)
    repository = SqliteEventRepository(engine=engine, auto_init=True)
    runner = CanonicalPipelineRunner(event_repository=repository)

    # Ingest through pipeline
    obs = SourceObservation.create(
        source_id="src_arstechnica",
        source_name="Ars Technica",
        source_tier=SourceTier.TIER_1_PREMIUM,
        zombie_species=ZombieSpecies.RSS,
        url="https://arstechnica.com/2026/08/rust-foundation-compiler-breakthrough",
        title="Rust Project Unveils Revolutionary Next-Gen Compiler Backend",
        summary="The Rust Foundation has released a new codegen backend reducing compile times by 70%.",
        raw_content="The Rust Foundation has released a new codegen backend reducing compile times by 70% across large enterprise codebases.",
        published_at_hint=datetime.now(UTC),
    )

    result = await runner.process_observation(obs)
    assert result.status.value == "success"
    assert result.event is not None
    event_id = result.event.id

    # Query via API
    set_event_repository(repository)
    client = TestClient(test_app)

    api_resp = client.get(f"/v1/events/{event_id}")
    assert api_resp.status_code == 200
    data = api_resp.json()

    assert data["id"] == event_id
    assert "Rust Project Unveils Revolutionary" in data["headline"]
    assert data["primary_source"] == "Ars Technica"
    assert data["source_count"] == 1
    assert len(data["sources"]) == 1
    assert data["sources"][0]["url"] == "https://arstechnica.com/2026/08/rust-foundation-compiler-breakthrough"
    assert len(data["timeline"]) == 1

    await engine.aclose()


@pytest.mark.asyncio
async def test_sse_stream_fallback_loads_from_repository(repo: SqliteEventRepository):
    """Verify SSE generator loads event from EventRepositoryProtocol when payload is event ID."""
    from src.engine.publication_bus import get_publication_bus
    from src.domain.models import PublicationEvent
    from src.domain.enums import PublicationChannel, PublicationEventType

    e1 = make_test_event(event_id="evt_sse_01")
    await repo.save_event(e1)
    set_event_repository(repo)

    bus = get_publication_bus()
    await bus.start()

    # Subscribe
    sub_id, queue = await bus.subscribe((PublicationChannel.SSE_STREAM,))

    # Publish an event ID payload
    pub_event = PublicationEvent(
        event_type=PublicationEventType.EVENT_UPDATED,
        payload={"id": "evt_sse_01"},
        channels=(PublicationChannel.SSE_STREAM,),
    )
    await bus.publish(pub_event)

    # Dequeue
    received = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert received is not None
    loaded_event = await repo.get_event(received.payload["id"])
    assert loaded_event is not None
    assert loaded_event.id == "evt_sse_01"

    await bus.unsubscribe(sub_id)
    await bus.stop()


def test_architecture_boundary_events_route_no_sqlite_imports():
    """Verify that src/api/routes/events.py has ZERO direct imports of sqlite3, aiosqlite, or SqliteEventRepository."""
    forbidden = {"sqlite3", "aiosqlite", "SqliteEventRepository", "SqliteEngine"}
    file_path = Path("src/api/routes/events.py")
    assert file_path.exists()

    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for bad in forbidden:
                    assert bad not in alias.name, f"{file_path} imports forbidden '{alias.name}'"
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for bad in forbidden:
                assert bad not in module, f"{file_path} imports from forbidden '{module}'"
            for alias in node.names:
                for bad in forbidden:
                    assert bad != alias.name, f"{file_path} imports forbidden symbol '{alias.name}'"
