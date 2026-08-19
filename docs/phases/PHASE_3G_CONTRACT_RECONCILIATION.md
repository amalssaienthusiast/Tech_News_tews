# Phase 3G Contract Reconciliation: Pre-Implementation Specification

**Document Version**: 1.0.0  
**Status**: APPROVED RECONCILIATION SPECIFICATION  
**Author**: Principal System Architect & Google DeepMind Antigravity  
**Target Subphase**: Subphase 3G (Pipeline Assembly & Runtime Integration)

---

## 1. Executive Summary & Purpose

This document resolves and formally locks all contract specifications, stage signatures, result conventions, execution boundaries, and feature-flag precedence before implementing Subphase 3G (`CanonicalPipelineRunner`, Stages S09–S11, and `UnifiedFeedChainEngine` integration).

---

## 2. Formal Stage Signatures (S01–S11)

All stages strictly implement `PipelineStage[T_in, T_out]` with the method:
```python
async def process(self, input_item: T_in, context: PipelineContext) -> Optional[T_out]: ...
```

| Stage | Name | Input Type | Output Type | Context Side-Effects / Metadata Key | Rejection Outcome |
|:---|:---|:---:|:---:|:---|:---|
| **S01** | `ObservationNormalizer` | `SourceObservation` | `NormalizedArticle` | None | Drops invalid/empty URL/title |
| **S02** | `FreshnessEvaluator` | `NormalizedArticle` | `NormalizedArticle` | `freshness_result: FreshnessResult` | Drops STALE (>72h) |
| **S03** | `TechRelevanceFilter` | `NormalizedArticle` | `NormalizedArticle` | `relevance_result: RelevanceResult` | Drops non-tech (<0.40) |
| **S04** | `QualityGate` | `NormalizedArticle` | `Tuple[NormalizedArticle, QualityReport]` | `quality_report: QualityReport` | Drops low quality (<0.50) |
| **S05** | `DedupEvaluator` | `NormalizedArticle` | `Tuple[NormalizedArticle, DedupDecision]` | `dedup_decision: DedupDecision` | Drops duplicate (`is_duplicate=True`) |
| **S06** | `DedupCommitter` | `NormalizedArticle` | `NormalizedArticle` | `dedup_committed: bool` | Skips commit if unpassed/dup |
| **S07** | `EventClusterer` | `NormalizedArticle` | `TechEvent` | `clustering_action`, `event_id` | N/A (creates/merges event) |
| **S08** | `ScoringEngine` | `TechEvent` | `TechEvent` | `scoring_metrics: Dict` | N/A (calculates scores) |
| **S09** | `EnrichmentStage` | `TechEvent` | `TechEvent` | `enrichment_status: str` | Bounded fallback on timeout |
| **S10** | `PersistenceStage` | `TechEvent` | `TechEvent` | `persisted_at: str` | N/A (persists aggregate) |
| **S11** | `PublicationStage` | `TechEvent` | `TechEvent` | `published_channels: List[str]` | N/A (dispatches to Bus) |

---

## 3. Stage Result vs. Runner Result Conventions

### 3.1 Stage-Level Convention: `Optional[T_out]`
- Stages **never** return `IngestionResult`.
- Every stage returns `Optional[T_out]` (or `Optional[Tuple[T_out, Metadata]]`).
- Rejection is represented uniformly across all stages:
  1. `context.abort(reason="...")` is called.
  2. The stage returns `None`.

### 3.2 Runner Output Unwrapping
`CanonicalPipelineRunner` safely unwraps stage return values to extract the primary domain object:
```python
def _unwrap_output(res: Any) -> Any:
    if res is None:
        return None
    if isinstance(res, tuple):
        return res[0]
    return res
```

### 3.3 Runner-Level Convention: `IngestionResult`
`CanonicalPipelineRunner.process_observation()` produces a comprehensive `IngestionResult` dataclass for callers, loggers, and metrics sinks:
```python
@dataclass(frozen=True, slots=True)
class IngestionResult:
    status: IngestionStatus                     # SUCCESS, DROPPED, ERROR
    event: Optional[TechEvent] = None
    rejected_at_stage: Optional[str] = None
    abort_reason: Optional[str] = None
    correlation_id: str = ""
    stage_metrics: Dict[str, float] = field(default_factory=dict)
    total_latency_ms: float = 0.0
```

---

## 4. S09 Bounded Asynchronous Enrichment Contract

1. **Definition**: Bounded asynchronous enrichment (maximum `2.0s` timeout per item).
2. **Execution**: The runner awaits S09 using `asyncio.wait_for(self.s09_enrichment.process(event, context), timeout=2.0)`.
3. **Timeout / Failure Fallback**:
   - If an external model or summarizer exceeds 2.0s or raises an error:
     - S09 catches the timeout/exception.
     - Logs a warning (`"S09 enrichment timed out; falling back to basic summary"`).
     - Returns the existing `TechEvent` intact with `enrichment_status="fallback"`.
   - Core ingestion is **never blocked or halted**.
4. **Concurrency Capacity**: `CanonicalPipelineRunner` bounds worker concurrency with `asyncio.Semaphore(16)`, ensuring ample worker capacity during bounded S09 awaits.

---

## 5. Shadow Mode Exact Scope & Invariants

```
Mode: "shadow"
Scope: Executes S01 -> S02 -> S03 -> S04 -> S05 -> S06 (dry-run) -> S07 -> S08
Disabled: S09 (Enrichment), S10 (Persistence), S11 (Publication)
Legacy Pipeline: Active (processes and publishes)
Dual-Publishing: ZERO (physically impossible because S11 is bypassed in shadow mode)
```

---

## 6. Priority-Aware PublicationBus Invariant

In `PublicationBus.publish()`:
1. `PublicationEvent.priority == PublicationPriority.HIGH` represents critical breaking news events (`TechEvent.is_breaking == True`).
2. High-priority events are tagged and routed through the bus.
3. In `DROP_OLDEST` queue overflow conditions, `QueueFull` evicts the oldest normal-priority event. High-priority breaking news events are preserved and delivered to subscribers.

---

## 7. Responsibilities & Ownership Separation

```
UnifiedFeedChainEngine (System Lifecycle Container)
├── Owns SourceRegistry, ZombieSwarm, PublicationBus, CanonicalPipelineRunner
├── Starts bus on initialize(), stops on stop()
└── Ingestion callback (_on_zombie_found_source):
      Converts EventSource -> SourceObservation and delegates to runner

CanonicalPipelineRunner (Ingestion Orchestration Engine)
├── Owns Stages S01–S11
├── Owns DedupIndex and ActiveEventStore
├── Instantiates execution-scoped PipelineContext per item
├── Enforces stage sequential loop, unwrapping, and early-drop exits
├── Enforces 2.0s S09 enrichment timeout
├── Enforces shadow-mode dry-run bypass of S09–S11
└── Isolates unhandled exceptions per item
```

---

## 8. Feature Flag Precedence

1. **`CANONICAL_PIPELINE_MODE`** (Environment Variable / Setting):
   - `"active"`: Canonical pipeline executes S01–S11 and publishes. Legacy publication disabled.
   - `"shadow"`: Canonical pipeline executes S01–S08 (dry-run). Legacy pipeline publishes.
   - `"legacy"`: 100% legacy pipeline execution. Canonical runner bypassed.
2. **`ENABLE_CANONICAL_PIPELINE`** (Boolean Fallback if `CANONICAL_PIPELINE_MODE` not set):
   - `True` -> Mode resolved to `"active"`.
   - `False` -> Mode resolved to `"legacy"` (default).

---

## 9. Shutdown & Cancellation Flow

1. `UnifiedFeedChainEngine.stop()`:
   - Sets `self.swarm.stop()` (crawler stops producing new observations).
   - Calls `await self.canonical_runner.stop(drain_timeout=5.0s)` to allow in-flight items to finish.
   - Calls `await self.bus.stop(drain_timeout=3.0s)` to drain subscriber queues and deliver final events.
   - Cleans up background tasks cleanly.
