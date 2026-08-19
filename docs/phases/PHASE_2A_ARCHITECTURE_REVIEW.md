# Phase 2A Architecture Review & Gate Evaluation

**Reviewer**: Principal Architect  
**Document Status**: Final Architectural Review  
**Target Specifications**: `PHASE_2A_ARCHITECTURE.md`, `PHASE_2A_CONTRACTS.md`, `PHASE_2A_MIGRATION_MAP.md`  
**Governing Principles**: `ENGINEERING_RULES.md`, `SYSTEM_REBUILD_AND_PRODUCTIONIZATION_PLAN.md`

---

## 1. Executive Review & Findings

The Phase 2A design establishes a robust, 5-layer Domain-Driven Design (DDD) foundation for the Tech News Scrapper rebuild. However, a rigorous audit identified several contract-level and boundary weaknesses in the initial draft that must be resolved before proceeding to Phase 2B implementation.

### Summary of Architectural Audit:

| Item | Focus Area | Status | Key Finding / Required Correction |
|:---|:---|:---:|:---|
| **1** | `SourceObservation` | 🟡 Needs Revision | Mutable `dict` in frozen dataclass (`metadata`, `headers`); identity calculation needs formal specification |
| **2** | `NormalizedArticle` | 🟡 Needs Revision | Mutable default lists; needs explicit canonical URL hashing and field ownership rules |
| **3** | `QualityReport` | 🟢 Validated | Scores bounded `[0.0, 1.0]`; explainable rejection codes; relevance and quality clearly decoupled |
| **4** | `DedupDecision` | 🟡 Needs Revision | Must explicitly split `evaluate()` from `commit()` to eliminate **dedup poisoning** |
| **5** | `FreshnessLevel` | 🟢 Validated | 8 temporal tiers locked; exact minute boundaries enforced; explicit policy for `UNKNOWN` undated items |
| **6** | `TechEvent` | 🟡 Needs Revision | `confidence`, `importance`, `freshness`, `novelty`, and `is_breaking` must be separated mathematically |
| **7** | `PublicationEvent` | 🔴 Critical Correction | Untyped `Dict[str, Any]` payload at the core boundary must be replaced with typed, discriminated models; add `schema_version` and `idempotency_key` |
| **8** | `SourceHealth` | 🟡 Needs Revision | Add formal state transition matrix; define explicit `PROBATION` state between `QUARANTINED` and `DEAD` |
| **9** | `PublicationBus` | 🟢 Validated | Application-scoped lifecycle, bounded subscriber queues (`maxsize=1000`), `DROP_OLDEST` slow-consumer policy, graceful shutdown |
| **10** | Layer Hierarchy | 🟢 Validated | 5-layer downward dependency model verified; zero cyclic dependencies |
| **11** | Migration & Boundaries | 🟢 Validated | Pre-implementation AST boundary tests specified; GUI isolated behind API client |

---

## 2. Detailed Point-by-Point Evaluation

### Point 1: `SourceObservation` Semantics
- **Finding**: In the initial draft, `headers: Dict[str, str]` and `metadata: Dict[str, Any]` were standard Python dictionaries. Inside a `@dataclass(frozen=True)`, standard dicts remain mutable, allowing downstream consumers to accidentally mutate observation data.
- **Decision**: Wrap dictionaries in read-only mapping proxies (`MappingProxyType`) or freeze them at construction. Identity `id` must be deterministic SHA-256 hash: `sha256(f"{source_id}|{url.strip().lower()}".encode()).hexdigest()[:20]`.

### Point 2: `NormalizedArticle` Semantics
- **Finding**: The article representation must have an immutable canonical URL identity and unambiguous timezone-aware timestamps (`discovered_at`, `extracted_at`, and optional `published_at`).
- **Decision**: Article ID is strictly `sha256(canonical_url.encode()).hexdigest()[:16]`. Field ownership belongs to the Normalizer stage; mutations for AI enrichment are modeled cleanly.

### Point 3: `QualityReport` Diagnostic Completeness
- **Finding**: Quality (technical hygiene, headline formatting, spam detection) and Relevance (is this content about technology/science?) must be treated as independent evaluation vectors.
- **Decision**: `QualityReport` retains two independent scores: `quality_score` (0.0–1.0) and `relevance_score` (0.0–1.0). Rejection codes are formalized as standardized string constants.

### Point 4: `DedupDecision` & Dedup Poisoning Prevention
- **Finding**: A critical flaw in legacy Pipeline 2 was that `dedup_gate.py` immediately added candidate URLs to its persistent seen database before quality filtering. Low-quality articles rejected downstream permanently poisoned the dedup index, preventing future high-quality coverage from being processed.
- **Decision**: Dedup Gate MUST expose two separate lifecycle methods:
  1. `evaluate(candidate) -> DedupDecision`: Read-only similarity check against existing index.
  2. `commit(decision, article)`: Writes to Bloom Filter and persistent MinHash index **only after** the article clears Quality, Relevance, and Freshness.

### Point 5: `FreshnessLevel` Locking & Unknown Handling
- **Finding**: Freshness boundaries must be deterministic and mutually exclusive.
- **Decision**:
  - `BREAKING`: `[0, 5]` minutes
  - `VERY_FRESH`: `(5, 30]` minutes
  - `FRESH`: `(30, 120]` minutes
  - `RECENT`: `(120, 360]` minutes (2–6 hours)
  - `AGING`: `(360, 1440]` minutes (6–24 hours)
  - `OLD`: `(1440, 4320]` minutes (24–72 hours)
  - `STALE`: `> 4320` minutes (> 72 hours) — rejected/archived
  - `UNKNOWN`: Undated articles. Policy: Disallowed in Breaking News pipeline; permitted in Standard pipeline if source tier is 1 or 2 and quality score ≥ 0.85.

### Point 6: `TechEvent` Intelligence Concepts
- **Finding**: The initial draft conflated `confidence` with `is_breaking`. Breaking news is a multi-dimensional state.
- **Decision**:
  - `confidence` (0.0–1.0): Factual certainty based on source tier weights and cross-source corroboration.
  - `importance` (0.0–1.0): Real-world impact score (e.g. major security advisory vs routine patch).
  - `freshness_score` (0.0–1.0): Temporal recency and velocity decay.
  - `novelty` (0.0–1.0): Dissimilarity from existing active event clusters.
  - `is_breaking` is a derived rule: `freshness == FreshnessLevel.BREAKING and confidence >= 0.70 and importance >= 0.60`.

### Point 7: `PublicationEvent` Type Safety
- **Finding**: `PublicationEvent.payload: Dict[str, Any]` was an untyped dictionary at the core architectural boundary.
- **Decision**: Use a typed discriminated union `PayloadType = Union[NormalizedArticle, TechEvent, SystemAlertPayload, SourceHealthPayload]`. Include `schema_version: int = 1` and `idempotency_key: str` for event deduplication on delivery surfaces.

### Point 8: `SourceHealth` State Machine & Dead Recovery
- **Finding**: `DEAD` state lacked explicit transition mechanics.
- **Decision**: Add a `PROBATION` state. When a `QUARANTINED` source (HTTP 404/410) reaches the end of its 7-day quarantine, it transitions to `PROBATION`. A single probe hunt is executed:
  - If probe succeeds -> transitions to `HEALTHY`.
  - If probe fails -> transitions to `DEAD` (requires manual administrative unquarantine).

### Point 9: `PublicationBus` Application-Scoped Architecture
- **Finding**: `PublicationBus` must be managed as an application-scoped lifecycle component (started/stopped with the application lifecycle), not an unmanaged global variable.
- **Decision**: Bounded subscriber queues (`maxsize=1000`). Slow-consumer policy: `DROP_OLDEST` with diagnostic logging. Clean asynchronous `drain()` and `stop()` semantics.

### Point 10 & 11: Architecture & Migration Integrity
- **Finding**: Layer boundaries and AST checks are fully sound.
- **Decision**: Pre-implementation AST test `tests/test_architecture_boundaries.py` will be committed and run in Phase 2B to verify that `src/domain/` imports zero external packages and `src/engine/` contains zero imports from `src/api/` or `gui_qt/`.
