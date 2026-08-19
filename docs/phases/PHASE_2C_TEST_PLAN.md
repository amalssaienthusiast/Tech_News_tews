# Phase 2C Test Plan: PublicationBus & Boundary Verification

**Document Status**: Phase 2C Test Specification  
**Authority**: Principal Architect  
**Scope**: Unit Tests, Integration Tests, AST Boundary Linters, and Regression Verification

---

## 1. Test Suite Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PHASE 2C TEST COVERAGE                          │
├────────────────────────────────────────────────────────────────────────┤
│ 1. tests/test_publication_bus.py                                       │
│    - Bus Lifecycle (start, stop, active state)                         │
│    - Publish / Subscribe Delivery Semantics                            │
│    - Channel Filtering (SSE, Telegram, WebSocket)                      │
│    - Priority Dispatching (HIGH, NORMAL, LOW)                          │
│    - Bounded Queues & DROP_OLDEST Slow Consumer Overflow               │
│    - Graceful Drain & Sentinel Shutdown                                │
│    - Consumer Idempotency Key Deduplication                            │
│                                                                        │
│ 2. tests/test_architecture_boundaries.py (Strengthened)                │
│    - AST Scan: src/engine/ has ZERO src.api or relative api imports     │
│    - AST Scan: src/engine/ has ZERO gui_qt imports                     │
│    - AST Scan: src/domain/ has ZERO outer-layer or network dependencies│
│    - AST Scan: src/core/ has ZERO delivery surface imports             │
│                                                                        │
│ 3. Cumulative Regression Suite                                         │
│    - All 87+ existing security, delivery, domain, and deployment tests │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Test Specifications

### 2.1 Unit Tests: `tests/test_publication_bus.py`

| Test Case | Description & Assertion |
|:---|:---|
| `test_bus_start_and_stop` | Verifies `bus.start()` marks `is_running=True` and `bus.stop()` gracefully shuts down internal workers. |
| `test_publish_and_subscribe_delivery` | Subscribes to `PublicationChannel.SSE_STREAM`, publishes an event, asserts event is received in subscriber queue. |
| `test_channel_filtering` | Subscribes Client A to `SSE_STREAM` and Client B to `TELEGRAM_BOT`. Publishes event targeted only to `TELEGRAM_BOT`. Asserts Client B receives it and Client A queue remains empty. |
| `test_slow_consumer_drop_oldest` | Sets subscriber `maxsize=3`. Publishes 5 events (E1, E2, E3, E4, E5). Asserts queue does NOT block publisher, queue size remains 3, oldest events (E1, E2) were dropped, and queue contains [E3, E4, E5]. |
| `test_unsubscribed_client_receives_no_events` | Registers subscriber, unsubscribes, publishes event, asserts queue remains empty and subscriber is removed from active registry. |
| `test_graceful_drain_on_stop` | Enqueues pending events, calls `bus.stop(drain_timeout=2.0)`, asserts pending items are drained before workers terminate. |
| `test_consumer_idempotency_dedup` | Consumer processes two events with identical `idempotency_key`, asserts only the first is handled and the duplicate is safely ignored. |
| `test_concurrent_multi_subscriber_fanout` | Spawns 10 concurrent subscribers across mixed channels, publishes 50 events concurrently, asserts correct fan-out delivery without race conditions. |

### 2.2 AST Boundary Tests: `tests/test_architecture_boundaries.py`

| Test Case | Description & Assertion |
|:---|:---|
| `test_engine_has_zero_api_imports` | Parses AST of all `.py` files in `src/engine/`. Asserts no `Import` or `ImportFrom` node references `src.api`, `api`, or `..api`. |
| `test_engine_has_zero_gui_imports` | Parses AST of all `.py` files in `src/engine/`. Asserts no import references `gui_qt`. |
| `test_domain_layer_purity` | Parses AST of all `.py` files in `src/domain/`. Asserts no import references outer layers or network libraries (`aiohttp`, `requests`, `fastapi`, `aiosqlite`, `asyncpg`). |
| `test_core_has_no_delivery_imports` | Parses AST of all `.py` files in `src/core/`. Asserts zero imports from `gui_qt`, `src.api`, or `telegram_feeder_bot`. |

---

## 3. Execution & Pass Criteria

Phase 2C is successful if:
1. `tests/test_publication_bus.py` passes 100% (all 8+ test cases).
2. `tests/test_architecture_boundaries.py` passes 100% (confirming 0 `engine -> api` imports).
3. Full cumulative test suite (95+ tests) passes with exit code 0.
4. Working tree is clean with granular commits on `rebuild/phase-2-domain-contracts`.
