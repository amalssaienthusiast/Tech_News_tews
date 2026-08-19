# Phase 2C Architecture: Boundary Isolation & Application-Scoped PublicationBus

**Document Status**: Phase 2C Design Specification  
**Authority**: Principal Architect  
**Scope**: PublicationBus Architecture, Engine-API Decoupling, Delivery Semantics, Inverted Dependency Resolution

---

## 1. Executive Summary

Phase 2C eliminates the critical architectural coupling between Layer 4 (Engine/Pipeline) and Layer 5 (API/Delivery surfaces). Specifically, it removes the direct function call `broadcast_event_update()` in `src/engine/unified_chain.py` that imported from `src/api/routes/events.py`, replacing it with an **asynchronous, application-scoped `PublicationBus`**.

```text
                               ┌─────────────────────────────────────────────────┐
                               │             CANONICAL DOMAIN TYPES              │
                               │        (PublicationEvent, PayloadType)          │
                               └────────────────────────┬────────────────────────┘
                                                        │ (depends on)
                                                        ▼
┌───────────────────────────────┐               ┌─────────────────────────────────┐
│ Layer 4: Pipeline & Engine    │───publish────►│    PublicationBus (Engine)      │
│ (src/engine/unified_chain.py) │               │ - App-scoped lifecycle          │
└───────────────────────────────┘               │ - Bounded queues (maxsize=1000) │
                                                │ - DROP_OLDEST on overflow       │
                                                │ - Channel filtering             │
                                                │ - Graceful drain on stop        │
                                                └────────────────┬────────────────┘
                                                                 │
                                                       subscribe │ fan-out
                                                                 ▼
                                                ┌─────────────────────────────────┐
                                                │ Layer 5: Delivery Surfaces      │
                                                │ - FastAPI SSE Routes            │
                                                │ - Telegram Feeder Bot           │
                                                │ - WebSocket Broadcasters        │
                                                │ - REST Feed Buffer              │
                                                └─────────────────────────────────┘
```

---

## 2. Core Architectural Design: `PublicationBus`

### 2.1 Application-Scoped Lifecycle
Rather than an unmanaged, mutable global variable, `PublicationBus` is designed as an **application-scoped lifecycle component**:
- **Instantiation**: Created during engine initialization (`UnifiedFeedChainEngine.__init__`) or API application lifespan (`app.state.publication_bus`).
- **Start**: `await publication_bus.start()` initializes dispatch queues and internal routing workers.
- **Stop**: `await publication_bus.stop(drain_timeout=5.0)` cleanly flushes pending events, cancels active subscriber queues, and releases resources.
- **Dependency Injection**: Subsystems receive the `PublicationBus` reference during initialization. A canonical singleton accessor `get_publication_bus()` is provided for backward-compatible module access while preserving explicit lifecycle ownership.

### 2.2 Bounded Subscriber Queues & Slow Consumer Policy (`DROP_OLDEST`)
To prevent memory leaks and eliminate Head-of-Line (HoL) blocking from slow consumers (e.g., a stalled SSE client or slow Telegram HTTP connection):
1. **Per-Subscriber Bounded Queue**: Every subscriber receives its own dedicated `asyncio.Queue(maxsize=1000)`.
2. **Atomic `DROP_OLDEST` Overflow Handling**:
   When a subscriber's queue reaches capacity (`maxsize`):
   - The bus immediately pops and discards the oldest pending event: `subscriber_queue.get_nowait()`.
   - The bus appends the new incoming event: `subscriber_queue.put_nowait(event)`.
   - The bus increments a `dropped_events_count` diagnostic metric on the subscriber registration.
   - If consecutive drops exceed 50, a structured warning is logged.
3. **Non-Blocking Publishing**: `await bus.publish(event)` never blocks or awaits subscriber consumption; it dispatches immediately to all eligible subscriber queues.

### 2.3 Channel Filtering & Priority Routing
Subscribers register with specific `PublicationChannel` subscriptions:
- `PublicationChannel.SSE_STREAM`: Real-time Server-Sent Events.
- `PublicationChannel.TELEGRAM_BOT`: Telegram delivery bot.
- `PublicationChannel.WEBSOCKET`: Real-time WebSocket clients.
- `PublicationChannel.FEED_BUFFER`: In-memory article ring buffer.

Events specify their target channels (`channels: Tuple[PublicationChannel, ...]`) and `priority: PublicationPriority` (`HIGH`, `NORMAL`, `LOW`). The bus routes events only to subscribers whose filter matches at least one target channel.

### 2.4 Graceful Drain and Shutdown Semantics
When the application stops:
1. `bus.stop(drain_timeout=5.0)` sets `_running = False`.
2. Disallows new `publish()` calls (raises `RuntimeError` or drops with warning).
3. Enqueues a sentinel (`None`) into all active subscriber queues.
4. Waits up to `drain_timeout` seconds for active subscriber tasks to process pending queue items.
5. Forcefully cancels any remaining worker tasks after timeout to guarantee deterministic shutdown.

---

## 3. Delivery Semantics & Consumer Idempotency

### 3.1 Typed `PublicationEvent` Envelope
All events passed through the bus are canonical `PublicationEvent` instances:
```python
PublicationEvent(
    event_id="pub_...",
    event_type=PublicationEventType.EVENT_DETECTED,
    schema_version=1,
    idempotency_key="event_detected:evt_12345",
    channels=(PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT),
    priority=PublicationPriority.HIGH,
    published_at=datetime.now(UTC),
    payload=tech_event,  # NormalizedArticle or TechEvent
)
```

### 3.2 Consumer-Side Idempotency
Every consumer (API SSE stream, Telegram Feeder Bot) maintains a bounded LRU/TTL deduplication set (`maxsize=5000`) of recently processed `idempotency_key`s.
- When an event arrives:
  1. Check if `event.idempotency_key in seen_keys`.
  2. If present -> skip processing (duplicate delivery discarded).
  3. If new -> add to `seen_keys` and dispatch to client.

---

## 4. Elimination of Boundary Violations

### 4.1 Remediation: `unified_chain.py` → `api.routes.events`
- **Current Problem**: `src/engine/unified_chain.py:108` executes `from ..api.routes.events import broadcast_event_update; broadcast_event_update(event.id)`.
- **Target Solution**:
  ```python
  # In src/engine/unified_chain.py:
  # Zero imports from src.api
  await self.bus.publish(
      PublicationEvent(
          event_type=PublicationEventType.EVENT_DETECTED if is_new else PublicationEventType.EVENT_UPDATED,
          payload=event,
          channels=(PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT),
          priority=PublicationPriority.HIGH if event.is_breaking else PublicationPriority.NORMAL,
      )
  )
  ```

### 4.2 Remediation: API / SSE Route Integration
- **Current Problem**: `src/api/routes/events.py` has an isolated module-level `_broadcaster` that was called directly by the engine.
- **Target Solution**:
  - `src/api/app.py` attaches a subscriber to `PublicationBus` during application lifespan.
  - The SSE endpoint `/v1/events/stream` subscribes to the bus and yields SSE formatted chunks (`event: event_update\ndata: ...`).

### 4.3 Remediation: Inverted Dependencies (`src/zombies/` → `src/engine/source_registry.py`)
- **Current Problem**: Zombie species imported `SourceDescriptor` and `SourceType` from `src.engine.source_registry`.
- **Target Solution**:
  - Re-export `SourceDescriptor` and `SourceType` from `src/domain/` or preserve alias in `src/engine/source_registry.py` while migrating canonical definitions to domain level.
  - Zombies only depend on Layer 1 (`src/domain/`).

---

## 5. Architectural Invariant Enforcement (AST Linter)

The AST boundary test `tests/test_architecture_boundaries.py` is strengthened in Phase 2C to assert:
1. `src/engine/` contains **ZERO** imports from `src.api` (both absolute and relative).
2. `src/engine/` contains **ZERO** imports from `gui_qt`.
3. `src/domain/` contains **ZERO** outer-layer or third-party network imports.
4. `src/core/` contains **ZERO** delivery surface imports (`src.api`, `gui_qt`, `telegram_feeder_bot`).
