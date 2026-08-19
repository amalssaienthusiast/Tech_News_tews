# Phase 3G Architectural Decisions Record

**Document Version**: 1.0.0  
**Status**: APPROVED DESIGN DECISIONS  
**Author**: Principal System Architect & Google DeepMind Antigravity  

---

## 1. The 20 Authoritative Decisions for Phase 3G

### Decision 1: Exact Ownership of `PipelineContext`
- `PipelineContext` is instantiated at **Ingress** (`CanonicalPipelineRunner.process_observation()`), strictly scoped to a single `SourceObservation` execution.
- It is passed sequentially through each stage (S01–S11).
- It is never stored in a global mutable container or shared across concurrent worker threads.

### Decision 2: Zombie Callback to `SourceObservation` Mapping
- In `_on_zombie_found_source(source)`, `SourceObservationAdapter.from_event_source(source)` converts the crawler's `EventSource` into the immutable, validated canonical domain contract `SourceObservation`.

### Decision 3: Stage Rejection Representation & Auditing
- When a filter stage rejects an item:
  - Calls `context.abort(reason="...")`.
  - Returns `None`.
  - `CanonicalPipelineRunner` catches `None`/aborted context, records stage rejection metrics (`rejected_at_stage`, `abort_reason`), and terminates processing for that item without raising an exception.

### Decision 4: Safe Drop Handling Without Exceptions
- All stages adhere to `PipelineStage[T_in, Optional[T_out]]`. Rejections produce clean early exits returning `IngestionResult.dropped()`, preventing error cascades and unhandled exceptions.

### Decision 5: Stage 6 (`DedupCommitter`) Receiving `QualityReport` from Stage 4 (`QualityGate`)
- S04 (`QualityGate`) stores `context.set("quality_report", report)`.
- S05 (`DedupEvaluator`) stores `context.set("dedup_decision", decision)`.
- S06 (`DedupCommitter`) retrieves both from context and mutates `DedupIndex` **only if** `quality_report.is_passed == True` and `dedup_decision.action == DedupAction.ACCEPTED` and `not is_duplicate`.

### Decision 6: TechEvent State Flow from S07 to S09/S10/S11
- S07 (`EventClusterer`) produces canonical `TechEvent`.
- S08 (`ScoringEngine`) receives `TechEvent`, attaches multi-dimensional scores (`confidence`, `importance`, `novelty`, `freshness_score`), and updates `is_breaking`.
- S09 (`EnrichmentStage`) receives scored `TechEvent` and performs bounded non-blocking enhancements.
- S10 (`PersistenceStage`) persists event updates to the event repository.
- S11 (`PublicationStage`) constructs a `PublicationEvent` and publishes to the `PublicationBus`.

### Decision 7: Application-Scoped `PublicationBus` Ownership
- `PublicationBus` is application-scoped and owned by `UnifiedFeedChainEngine` (via `get_publication_bus()`).
- Injected directly into S11. The pipeline does not maintain a private unmanaged event bus.

### Decision 8: Canonical Pipeline Runner Lifecycle
- `CanonicalPipelineRunner` is instantiated during engine initialization (`UnifiedFeedChainEngine.initialize()`), holding references to shared stage stores (`DedupIndex`, `ActiveEventStore`) and stages S01–S11.

### Decision 9: Startup & Shutdown Behavior
- **Startup**: `initialize()` instantiates the runner, registers stages, attaches state stores, and starts the `PublicationBus`.
- **Shutdown**: `stop()` flushes in-flight tasks, logs pending telemetry, and stops the bus.

### Decision 10: Concurrency Model
- Ingestion tasks run asynchronously. Shared stores (`DedupIndex`, `ActiveEventStore`) are protected by internal `threading.RLock()`, guaranteeing thread-safe and coroutine-safe operations across parallel workers.

### Decision 11: Backpressure Behavior
- Bounded ingestion concurrency via `asyncio.Semaphore(16)`.
- Ring-buffer queue (`MAX_QUEUE_SIZE = 1000`) in `PublicationBus` with `DROP_OLDEST` policy for normal priority and guaranteed delivery for high priority breaking events.

### Decision 12: Error Isolation
- Ingestion execution is wrapped in a `try...except Exception as e:` block. An error processing one item logs an error result and never crashes or halts the pipeline runner.

### Decision 13: Per-Item Tracing & Metrics
- `PipelineContext` tracks `pipeline_id`, `correlation_id`, `started_at`, and `stage_metrics: Dict[str, float]` recording latency per stage on every item.

### Decision 14: Feature Flag `ENABLE_CANONICAL_PIPELINE`
- Controlled via `ENABLE_CANONICAL_PIPELINE` (bool) and `CANONICAL_PIPELINE_MODE` (`"active"`, `"shadow"`, `"legacy"`).

### Decision 15: Legacy Fallback Behavior
- When `ENABLE_CANONICAL_PIPELINE=False` or mode is `"legacy"`, 100% of ingestion runs through the legacy pipeline path.

### Decision 16: Shadow / Dual-Run Strategy
- In `"shadow"` mode:
  - Canonical pipeline executes S01–S08 for latency/quality telemetry with publication disabled (`dry_run=True`).
  - Legacy pipeline executes and publishes.
  - In `"active"` mode: Canonical pipeline executes S01–S11 and publishes; legacy publication is disabled.
  - **Zero Duplicate Publication Invariant**: Exactly one pipeline publishes per run mode.

### Decision 17: Exact Changes Allowed in `unified_chain.py`
- Wire `CanonicalPipelineRunner` in `initialize()`, route in `_on_zombie_found_source()`, and stop in `stop()`.
- Zero alterations to legacy classes (`FeedChain`, `DedupGate`, `QualityGate`, `ContentEnhancer`).

### Decision 18: Persistence Boundary
- S10 persistence interfaces with the existing storage/repository contracts without modifying SQLite/Postgres schemas or storage internals in Phase 3.

### Decision 19: Enrichment Isolation
- S09 enrichment executes with a strict timeout (2.0s). If an external summarizer/enricher fails or times out, it gracefully falls back without blocking core pipeline ingestion.

### Decision 20: Rollback Procedure
- Immediate zero-downtime rollback by toggling `ENABLE_CANONICAL_PIPELINE=False` without requiring code reversion or database migrations.
