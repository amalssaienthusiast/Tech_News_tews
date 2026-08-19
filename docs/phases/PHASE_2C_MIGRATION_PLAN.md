# Phase 2C Migration Plan: Engine-API Decoupling

**Document Status**: Phase 2C Implementation Plan  
**Authority**: Principal Architect  
**Scope**: Step-by-Step Execution Plan for Boundary Decoupling and PublicationBus Integration

---

## 1. Migration Overview & Target State

Phase 2C completes the boundary isolation of the core engine by introducing the `PublicationBus` and eliminating all remaining upward layer dependencies (`src/engine/` -> `src/api/`).

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PHASE 2C MIGRATION STEPS                        │
├────────────────────────────────────────────────────────────────────────┤
│ Step 1: Implement PublicationBus (src/engine/publication_bus.py)       │
│ Step 2: Create PublicationBus Unit Test Suite (test_publication_bus.py)│
│ Step 3: Decouple UnifiedChain (remove lazy API import, publish to bus) │
│ Step 4: Wire API Routes to PublicationBus Subscriber                   │
│ Step 5: Strengthen Architecture AST Boundary Tests                     │
│ Step 6: Full Regression Verification & Gate Approval                   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Granular Step-by-Step Execution

### Step 1: Implement `src/engine/publication_bus.py`
Create the application-scoped `PublicationBus` class with:
- `Subscription` dataclass: `subscriber_id: str`, `channels: Set[PublicationChannel]`, `queue: asyncio.Queue`, `dropped_count: int`.
- `PublicationBus` methods:
  - `subscribe(subscriber_id: str, channels: Tuple[PublicationChannel, ...], maxsize: int = 1000) -> asyncio.Queue`
  - `unsubscribe(subscriber_id: str) -> None`
  - `publish(event: PublicationEvent) -> None` (atomic, non-blocking, `DROP_OLDEST` overflow handling)
  - `start() -> None` and `stop(drain_timeout: float = 5.0) -> None`
- Canonical factory / singleton accessor: `get_publication_bus()`.

### Step 2: Implement Test Suite `tests/test_publication_bus.py`
Develop comprehensive asynchronous test suite validating:
- Asynchronous publish-subscribe event delivery.
- Multi-channel filtering (subscribers only receive matching channels).
- Priority ordering (`HIGH`, `NORMAL`, `LOW`).
- Bounded queue overflow (`DROP_OLDEST`) without blocking publisher or throwing unhandled errors.
- Graceful shutdown and queue drain.
- Consumer idempotency key deduplication.

### Step 3: Decouple `src/engine/unified_chain.py`
- In `UnifiedFeedChainEngine.__init__`:
  - Attach `self.bus = get_publication_bus()`.
- In `_on_zombie_found_source(self, source)`:
  - **DELETE** `from ..api.routes.events import broadcast_event_update; broadcast_event_update(event.id)`.
  - **ADD** `await self.bus.publish(...)` using canonical `PublicationEvent`.

### Step 4: Wire `src/api/routes/events.py` to `PublicationBus`
- Modify the SSE streaming route `/v1/events/stream` to subscribe to `PublicationBus` for `PublicationChannel.SSE_STREAM`.
- Maintain identical SSE chunk format (`event: event_update\ndata: { ... }\n\n`) ensuring zero breaking changes for existing frontend/SSE consumers.
- Ensure proper cleanup (`bus.unsubscribe(...)`) in `finally` block when SSE client disconnects.

### Step 5: Strengthen AST Architecture Boundary Tests
Update `tests/test_architecture_boundaries.py` to include:
- `test_engine_has_zero_api_imports`: Scans all `.py` files in `src/engine/` using `ast.parse` and asserts zero `src.api` or relative `api` imports.
- `test_engine_has_zero_gui_imports`: Asserts zero `gui_qt` imports in `src/engine/`.
- `test_domain_purity`: Asserts `src/domain/` has zero outer-layer or network dependencies.

### Step 6: Full Regression Verification
Run the cumulative test suite across:
- Security policy (`test_security_policy.py`, `test_api_security.py`)
- TLS verification (`test_tls_verification.py`)
- Telegram delivery integration (`test_telegram_integration.py`)
- Deployment baseline (`test_deployment_baseline.py`)
- Domain contracts (`test_domain_contracts.py`)
- PublicationBus (`test_publication_bus.py`)
- Architecture boundaries (`test_architecture_boundaries.py`)

---

## 3. Allowed vs. Prohibited Scope Matrix

| Action | Allowed in Phase 2C? | Reason / Constraint |
|:---|:---:|:---|
| Create `src/engine/publication_bus.py` | ✅ YES | Core objective: decouple engine from API |
| Create `tests/test_publication_bus.py` | ✅ YES | Verifies bus lifecycle and backpressure |
| Edit `src/engine/unified_chain.py` (L108 API import removal only) | ✅ YES | Eliminates boundary violation |
| Edit `src/api/routes/events.py` (wire to bus) | ✅ YES | Connects delivery to bus subscriber |
| Strengthen `tests/test_architecture_boundaries.py` | ✅ YES | Enforces boundary in automated CI |
| Refactor Zombie species | ❌ NO | Deferred to Phase 5 |
| Rewrite pipeline gates (`dedup_gate.py`, etc.) | ❌ NO | Deferred to Phase 3 |
| Migrate database persistence | ❌ NO | Deferred to Phase 6 |
| Modify GUI code (`gui_qt/`) | ❌ NO | Deferred to Phase 8 |
| Introduce Redis/Kafka/Celery | ❌ NO | Out of scope for in-process bus |
| Upgrade dependencies | ❌ NO | Prohibited by Engineering Rules |
