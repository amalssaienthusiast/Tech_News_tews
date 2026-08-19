# Phase 2C Implementation Report: Engine-API Decoupling & PublicationBus

**Date**: 2026-08-14  
**Status**: COMPLETED & VERIFIED ✅  
**Branch**: `rebuild/phase-2-domain-contracts`  
**Commit SHA**: `f304ed8`  
**Base Commit**: `36c11cf`

---

## 1. Executive Summary

Phase 2C successfully eliminated the circular runtime dependency and upward layer coupling between `src/engine/unified_chain.py` (Layer 4) and `src/api/routes/events.py` (Layer 5). 

The direct call `from ..api.routes.events import broadcast_event_update` has been replaced by the **application-scoped `PublicationBus`**, enabling pure, non-blocking asynchronous pub/sub delivery with `DROP_OLDEST` backpressure mitigation, channel filtering, consumer idempotency, and graceful drain capabilities.

---

## 2. Implementation Deliverables

| Component | Target File | Status | Key Deliverable |
|:---|:---|:---:|:---|
| **PublicationBus** | `src/engine/publication_bus.py` | ✅ | Application-scoped asynchronous event bus; bounded queues (`maxsize=1000`); `DROP_OLDEST` slow-consumer policy; channel filtering (`PublicationChannel`); graceful 5.0s drain timeout; idempotency tracking. |
| **Engine Decoupling** | `src/engine/unified_chain.py` | ✅ | Removed line 108 lazy import of `broadcast_event_update`. Integrated `PublicationBus.publish()` with canonical `PublicationEvent`. |
| **SSE Route Wiring** | `src/api/routes/events.py` | ✅ | SSE streaming endpoint `/v1/events/stream` subscribes to `PublicationBus` (`SSE_STREAM` channel); backward-compatible bridge for `broadcast_event_update()`. |
| **PublicationBus Tests** | `tests/test_publication_bus.py` | ✅ | 7 targeted tests covering lifecycle, channel filtering, priority routing, bounded queue overflow (`DROP_OLDEST`), drain/stop, and idempotency deduplication. |
| **Boundary Tests** | `tests/test_architecture_boundaries.py` | ✅ | Strengthened AST tests asserting `src/engine/` contains zero imports from `src.api` (absolute or relative) and zero imports from `gui_qt`. |

---

## 3. Test Suite Execution Results

### 3.1 Targeted Boundary & PublicationBus Tests (12/12 PASSED)
```text
============================= test session starts ==============================
collected 12 items

tests/test_architecture_boundaries.py .....                              [ 41%]
tests/test_publication_bus.py .......                                    [100%]

============================== 12 passed in 6.10s ==============================
```

### 3.2 Full Cumulative Rebuild Test Suite (95/95 PASSED)
```text
============================= test session starts ==============================
collected 95 items

tests/test_security_policy.py .............................              [ 30%]
tests/test_tls_verification.py ......                                    [ 36%]
tests/test_api_security.py ........                                      [ 45%]
tests/test_telegram_integration.py .........                             [ 54%]
tests/test_deployment_baseline.py .....                                  [ 60%]
tests/test_domain_contracts.py ..........................                [ 87%]
tests/test_architecture_boundaries.py .....                              [ 92%]
tests/test_publication_bus.py .......                                    [100%]

============================== 95 passed in 8.55s ==============================
```

---

## 4. Scope & Boundary Invariant Verification

- **Allowed Files Modified Only**: Zero changes to `src/zombies/`, `dedup_gate.py`, `quality_gate.py`, database persistence, `gui_qt/`, or external dependencies.
- **AST Architecture Verification**: Static AST analysis confirms `src/engine/` contains **0 imports** from `src.api` and `0 imports` from `gui_qt`.
- **Zero Breaking Changes**: Server-Sent Events output format and Telegram delivery behavior remain 100% backward-compatible.

---

## 5. Next Steps

Phase 2 (Domain Contracts, Boundary Isolation & PublicationBus) is **FULLY COMPLETED**.
Proceed to **Phase 3 (Canonical Sequential Pipeline)**.
