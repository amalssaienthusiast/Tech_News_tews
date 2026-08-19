# Phase 2A Migration Map & Component Integration Plan

**Document Status**: Phase 2A Design Specification  
**Authority**: Architecture Lead  
**Scope**: Component Migration Sequence, Boundary Violation Elimination, Backward Compatibility, and Test Specification

---

## 1. Component State Mapping (Current vs. Target)

| Component / Subsystem | Current File(s) | Target Canonical Module | Status & Migration Strategy |
|:---|:---|:---|:---|
| **Domain Contracts** | Fragmented in `src/core/types.py`, `src/events/event_types.py`, `src/core/protocol.py` | `src/domain/` (`models.py`, `enums.py`, `events.py`, `validators.py`) | Create clean, unified domain package in Phase 2B. Re-export legacy aliases in `src/core/types.py` for backward compatibility until Phase 8. |
| **Publication Bus** | Ad-hoc `broadcast_event_update` in API route, `FeedChain` callback | `src/engine/publication_bus.py` | Create asynchronous `PublicationBus` singleton. Decouples pipeline from API routes and delivery channels. |
| **Zombie Collectors** | `src/zombies/zombie_base.py`, `src/zombies/z_*.py` | `src/zombies/` | Refactor `ZombieBase.hunt()` to return `List[SourceObservation]`. Eliminate raw dicts and ad-hoc `EventSource` instantiations. |
| **Pipeline & Gates** | `src/engine/unified_chain.py`, `dedup_gate.py`, `quality_gate.py`, `quality_filter.py` | `src/engine/` (Phase 3) | Connect pipeline sequentially: `SourceObservation -> Normalizer -> FreshnessGate -> RelevanceGate -> QualityGate -> DedupGate -> EventClusterer -> PublicationBus`. |
| **Event Brain** | `src/events/event_clusterer.py`, `confidence_engine.py`, `freshness_gate.py` | `src/events/` | Refactor `EventClusterer` to consume `NormalizedArticle` and update `TechEvent` aggregates. Remove all imports from `src/api/`. |
| **Delivery: API / SSE** | `src/api/app.py`, `src/api/routes/events.py`, `src/realtime/sse_broadcaster.py` | `src/api/` | In `app.py` lifespan, subscribe to `PublicationBus`. Dispatch SSE/WS on incoming `PublicationEvent`. Delete direct function calls from engine. |
| **Delivery: Telegram Bot**| `telegram_feeder_bot.py` | `telegram_feeder_bot.py` | Subscribes to engine's `/api/v1/stream` (SSE) or local `PublicationBus`. Consumes `PublicationEvent`. |
| **Desktop GUI** | `gui_qt/` | `gui_qt/` (Isolated) | GUI communicates exclusively via HTTP/SSE API client. Zero server-side imports from `gui_qt/`. |

---

## 2. Step-by-Step Migration Sequence

```text
Step 1: Domain Package Implementation (Phase 2B)
  - Create src/domain/ with 8 canonical contracts
  - Create test_domain_contracts.py (100% invariant & serialization test coverage)
  - Add compatibility re-exports in src/core/types.py

Step 2: Publication Bus Implementation (Phase 2B/2C)
  - Create src/engine/publication_bus.py
  - Create test_publication_bus.py (async pub/sub, channel filtering, bounded queues)

Step 3: Boundary Violation Cleanup (Phase 2C)
  - Replace broadcast_event_update call in unified_chain.py with bus.publish()
  - Verify zero engine -> API imports via AST tests

Step 4: Pipeline Ingestion Refactoring (Phase 3)
  - Transition Zombies to emit SourceObservation
  - Implement Normalizer stage producing NormalizedArticle
  - Connect sequential pipeline gates

Step 5: Event Brain & Storage Refactoring (Phase 4-6)
  - EventClusterer operates on NormalizedArticle -> TechEvent
  - AsyncDatabase persistence consumes TechEvent and NormalizedArticle
```

---

## 3. Boundary Violation Elimination Verification

### 3.1 Verification of Engine → API Decoupling
```python
# In src/engine/unified_chain.py:
# BEFORE (Violation):
# from ..api.routes.events import broadcast_event_update
# broadcast_event_update(event.id)

# AFTER (Decoupled):
await publication_bus.publish(
    PublicationEvent(
        event_id=str(uuid4()),
        event_type=PublicationEventType.EVENT_DETECTED if is_new else PublicationEventType.EVENT_UPDATED,
        payload=event.to_dict(),
        channels=(PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT),
        priority=PublicationPriority.HIGH if event.is_breaking else PublicationPriority.NORMAL,
    )
)
```

### 3.2 Automated AST Import Boundary Test
To guarantee architectural integrity, a dedicated AST linter test will run on every test execution:

```python
# tests/test_architecture_boundaries.py
def test_engine_has_no_api_imports():
    """Verify src/engine/ never imports from src/api/."""
    engine_files = list(Path("src/engine").glob("*.py"))
    for file_path in engine_files:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert not name.name.startswith("src.api"), f"{file_path} imports {name.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not "api" in node.module, f"{file_path} imports from {node.module}"
```

---

## 4. Required Phase 2 Test Specifications

When Phase 2 implementation begins, the following test suites must be developed and passed:

1. **`tests/test_domain_contracts.py`**:
   - `test_source_observation_invariants`: Rejects empty URL/title, validates timezone-aware UTC.
   - `test_normalized_article_canonicalization`: Validates scheme/host lowercasing and tracking parameter stripping.
   - `test_quality_report_rejection_reasons`: Validates that rejected reports always contain non-empty reason codes.
   - `test_dedup_decision_invariants`: Validates similarity score ranges and action semantics.
   - `test_freshness_level_boundaries`: Tests exact age boundaries (0-5m BREAKING, 5-30m VERY_FRESH, etc., and >72h STALE).
   - `test_tech_event_aggregation`: Tests adding sources, deduplication of source URLs, timeline sorting, and breaking score computation.
   - `test_source_health_state_machine`: Tests failure transitions (`HEALTHY -> DEGRADED -> COOLDOWN -> QUARANTINED`) and recovery.
   - `test_serialization_roundtrip`: Verifies `to_dict()` and `from_dict()` for all domain models.

2. **`tests/test_publication_bus.py`**:
   - `test_bus_publish_subscribe`: Validates async subscriber receives published events.
   - `test_channel_filtering`: Validates subscribers only receive events for subscribed channels.
   - `test_bounded_queue_backpressure`: Validates slow subscribers do not exhaust memory.
   - `test_graceful_shutdown`: Validates that shutting down the bus flushes pending events.

3. **`tests/test_architecture_boundaries.py`**:
   - `test_engine_does_not_import_api`
   - `test_domain_has_zero_external_dependencies`
   - `test_gui_has_no_server_imports`
