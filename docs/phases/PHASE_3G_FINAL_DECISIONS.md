# Phase 3G Final Decisions Record

**Document Version**: 1.0.0  
**Status**: AUTHORITATIVE & RATIFIED  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. Ratified Decisions for Phase 3G Implementation

### 1. Stage Signatures & Types
- All pipeline stages S01–S11 adhere strictly to `PipelineStage[T_in, T_out]`.
- Stages return `Optional[T_out]` (or `Optional[Tuple[T_out, Metadata]]`).
- Rejection is signaled by returning `None` and calling `context.abort(reason)`.

### 2. Stage Result Unwrapping & IngestionResult
- Individual stages **never** return `IngestionResult`.
- The runner unwraps tuples using `_unwrap_output(res)` to seamlessly pass the primary domain object to subsequent stages.
- The runner produces a structured `IngestionResult` (`SUCCESS`, `DROPPED`, `ERROR`) for caller observability.

### 3. Bounded Asynchronous Enrichment (S09)
- S09 executes with a strict `2.0s` timeout.
- On timeout or error, S09 immediately returns the original `TechEvent` with `enrichment_status="fallback"`.
- Core ingestion is never blocked.

### 4. Shadow Mode Scope
- In `"shadow"` mode, canonical pipeline executes S01 through S08 only for telemetry/metrics.
- Stages S09, S10, and S11 are completely skipped (`dry_run=True`).
- Legacy pipeline publishes; canonical pipeline does not.

### 5. Priority-Aware Publication
- S11 sets `PublicationPriority.HIGH` for breaking news (`TechEvent.is_breaking == True`).
- `PublicationBus` preserves high-priority breaking news during buffer congestion.

### 6. Orchestration Boundary
- `CanonicalPipelineRunner` owns 100% of pipeline orchestration, stage execution, context scoping, and error handling.
- `UnifiedFeedChainEngine` acts purely as the application container and callback router.

### 7. Feature Flag Resolution Order
- `CANONICAL_PIPELINE_MODE` (`"active"`, `"shadow"`, `"legacy"`) takes first priority.
- `ENABLE_CANONICAL_PIPELINE` (`True` -> `"active"`, `False` -> `"legacy"`) serves as fallback.

### 8. Zero Dual Publication
- Publication is mutually exclusive: only active mode publishes canonical events; only shadow/legacy modes publish legacy events.

### 9. Orderly Shutdown
- Clean hierarchical draining: Swarm stops -> Runner drains in-flight items -> Bus drains subscriber queues -> Background tasks complete.

---

## 2. Gate Verification Sign-Off

The Phase 3G contracts, stage signatures, runner boundaries, and test requirements are fully reconciled and locked.

**Verdict: APPROVE 3G FOR IMPLEMENTATION**
