# Phase 2C Architectural Decisions & Approval Gate

**Authority**: Principal Architect  
**Date**: 2026-08-14  
**Verdict**: **APPROVE FOR IMPLEMENTATION** ✅

---

## 1. Architectural Verdict

The architecture and design for Phase 2C (Boundary Isolation & Application-Scoped PublicationBus) is **APPROVED FOR IMPLEMENTATION**.

Phase 2C completes the decoupling of Layer 4 (Engine) and Layer 5 (API/Delivery) by replacing direct route invocations with the `PublicationBus` pub/sub pattern while strictly preserving all external API and delivery semantics.

---

## 2. Key Decisions & Requirements Summary

| Requirement Area | Architectural Decision |
|:---|:---|
| **1. PublicationBus Scope** | Application-scoped lifecycle (`start()`, `stop()`), owned by Engine/App runtime; clean singleton accessor `get_publication_bus()` provided for module compatibility. |
| **2. Engine → API Decoupling** | Removed `from ..api.routes.events import broadcast_event_update` in `unified_chain.py`. Replaced with `await self.bus.publish(PublicationEvent(...))`. |
| **3. Typed Event Delivery** | Dispatches canonical `PublicationEvent` with `schema_version=1`, `idempotency_key`, `channels`, `priority`, and typed `payload`. |
| **4. Subscriber Lifecycle** | Bounded per-subscriber queues (`asyncio.Queue(maxsize=1000)`). Explicit `subscribe()` and `unsubscribe()` registration. |
| **5. Slow Consumer Policy** | **`DROP_OLDEST`**: When queue is full, evicts oldest pending event, appends incoming event, increments drop diagnostic counter, and avoids blocking publisher. |
| **6. Graceful Shutdown** | `stop(drain_timeout=5.0)` sets `_running=False`, injects sentinel into subscriber queues, flushes pending tasks up to timeout, and closes resources. |
| **7. Consumer Idempotency** | Consumers filter duplicate deliveries using a bounded LRU/TTL set on `event.idempotency_key`. |
| **8. API / SSE Integration** | FastAPI SSE streaming route `/v1/events/stream` subscribes to `PublicationBus` and formats chunks identically to maintain frontend compatibility. |
| **9. Telegram Boundary** | Telegram feeder bot consumes events via authenticated HTTP SSE `/api/v1/stream` (standalone mode) or in-process `PublicationBus` (embedded mode). |
| **10. Inverted Dependencies** | Re-exported `SourceDescriptor` and `SourceType` from `src/domain/` to ensure zombies/events depend strictly on Layer 1. |
| **11. AST Boundary Tests** | Automated AST tests verify zero `src.api` or relative `api` imports in `src/engine/` and zero `gui_qt` imports in `src/engine/`. |

---

## 3. Strict Boundary Rules for Phase 2C Implementation

Gemini 3.6 Flash is authorized to implement Phase 2C strictly within the following files:

### Allowed Files:
1. `src/engine/publication_bus.py` [NEW]
2. `src/engine/unified_chain.py` [MODIFY - Line 108 API import removal only]
3. `src/api/routes/events.py` [MODIFY - wire SSE route to PublicationBus]
4. `tests/test_publication_bus.py` [NEW]
5. `tests/test_architecture_boundaries.py` [MODIFY - add engine->api AST check]

### FORBIDDEN During Phase 2C:
- ❌ DO NOT refactor Zombie species (Phase 5)
- ❌ DO NOT rewrite pipeline gates like `dedup_gate.py` or `quality_gate.py` (Phase 3)
- ❌ DO NOT modify database persistence engines (Phase 6)
- ❌ DO NOT modify Desktop GUI code in `gui_qt/` (Phase 8)
- ❌ DO NOT introduce Redis / Celery / Kafka
- ❌ DO NOT upgrade third-party dependencies
- ❌ DO NOT perform unrelated cleanups
