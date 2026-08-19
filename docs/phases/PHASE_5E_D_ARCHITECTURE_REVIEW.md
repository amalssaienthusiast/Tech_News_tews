# Phase 5E-D Architecture Review: Source Health & Swarm Lifecycle Integration

**Document Version:** 1.0.0  
**Author:** Antigravity Principal Systems Architect & Storage Reviewer  
**Date:** 2026-08-15  
**Baseline Git Commit:** `04f42ac` (Subphases 5E-A, 5E-B, and 5E-C committed & clean)  
**Cumulative Test Baseline:** `315/315 PASSED`  
**Status:** **APPROVED FOR IMPLEMENTATION**  

---

## 1. Executive Summary & Verdict

Subphase 5E-D designs the lifecycle integration of the canonical asynchronous [`SourceHealthRepositoryProtocol`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/protocols.py#L138-L167) (implemented in 5E-B via [`SqliteSourceHealthRepository`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/sqlite_source_health_repository.py#L50-L210)) with the acquisition layer ([`ZombieSwarm`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/swarm.py#L33-L164) and [`SourceRegistry`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/source_registry.py#L88-L255)).

```text
               UnifiedFeedChainEngine
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
  SourceRegistry                     ZombieSwarm
  (Descriptor Config)           (Supervisory Orchestrator)
        │                                 │
        │                        ┌────────┴────────┐
        │                        ▼                 ▼
        │              Hydrate / Persist       Hunt Workers
        │                        │          (ZRss, ZWeb, etc.)
        │                        ▼                 │
        │             SourceHealthRepository       │
        │          (SourceHealthRepositoryProtocol)│
        │                        │                 │
        ▼                        ▼                 ▼
   Custom JSON        canonical_source_health   SourceObservation
 (data/custom_sources) (data/canonical_events.db)  ↓
                                                Canonical Pipeline (S01-S11)
```

**Final Verdict:** **APPROVED FOR IMPLEMENTATION**

---

## 2. Answers to Architecture Review Questions

### 1. Where is SourceHealth currently created and mutated?
- **Domain Model:** Defined in [`src/domain/models.py:674–804`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L674-L804) as `SourceHealth`. It encapsulates operational state machine transitions via `record_success(working_tier)` and `record_failure(status_code, retry_after_sec)`.
- **Runtime Descriptor:** [`SourceRegistry`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/source_registry.py#L30-L81) currently tracks mirror fields inside `SourceDescriptor` (`consecutive_failures`, `last_attempt`, `last_success`, `cooldown_until`, `is_blacklisted`).
- **Legacy Monitor:** [`src/resilience/source_health.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/resilience/source_health.py#L25-L100) contains an in-memory `SourceHealthMonitor` that computed sliding-window success rates.

### 2. Where are hunt attempts recorded?
- In [`ZombieBase.start_hunting()`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/zombie_base.py#L53-L102), each iteration through the `while self.is_running:` loop executes `await self.hunt()`.
- Each invocation represents a discrete hunt attempt for the zombie's target `SourceDescriptor`.

### 3. Where are success/failure outcomes available?
- In `ZombieBase.start_hunting()`:
  - **Success:** When `new_sources = await self.hunt()` completes without error and returns 0 or more `SourceObservation` entities.
  - **Failure:** When `await self.hunt()` raises an unhandled exception (e.g. network timeout, TLS error, parse failure) or when `BypassResolver.fetch()` exhausts all bypass tiers and returns `None`.
- In `BypassResolver._escalated_fetch()`: When a tier returns valid content, `source.last_working_tier` is recorded.

### 4. Where are HTTP status codes available?
- In [`BypassResolver._attempt_tier()`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/bypass_resolver.py#L113-L165):
  - Tier 0 (`aiohttp`): `resp.status`
  - Tier 1 (`primp`): `resp.status_code`
- In API zombies ([`ZGitHub`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/z_github.py) and [`ZHacker`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/z_hacker.py)): HTTP response statuses from direct endpoints.

### 5. Where are 429/rate-limit events available?
- Within the HTTP response status code `429` (Too Many Requests), with optional `Retry-After` header.
- Handled by `SourceHealth.record_failure(status_code=429, retry_after_sec=...)` which transitions the source status to `SourceHealthStatus.RATE_LIMITED` and calculates `cooldown_until` / `rate_limit_reset_at`.

### 6. Where are cooldown/quarantine decisions currently made?
- In [`SourceHealth.record_failure()`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L725-L753):
  - HTTP `404`/`410` $\to$ `QUARANTINED` (7-day quarantine).
  - HTTP `429` $\to$ `RATE_LIMITED` (retry-after backoff, default 300s).
  - $\ge 5$ consecutive failures $\to$ `COOLDOWN` ($2^{f-5} \times 5$ minutes, max 360 min).
  - $1..4$ consecutive failures $\to$ `DEGRADED`.
  - Failed probe on probation $\to$ `DEAD`.
- In [`ZombieBase.start_hunting()`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/zombie_base.py#L69-L73): Cooldown sleep check before hunting (`if self.source.cooldown_until > now: sleep`).

### 7. Which component owns source lifecycle state?
- **Domain State:** [`SourceHealth`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/domain/models.py#L674) owns the state machine logic.
- **Orchestration Lifecycle:** [`ZombieSwarm`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/swarm.py#L33) supervises all active zombies and coordinates between source definitions and runtime execution.
- **Registry:** [`SourceRegistry`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/source_registry.py#L88) is the source configuration authority.

### 8. Which component should own persistence?
- **Decision:** [`ZombieSwarm`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/swarm.py#L33) must own the injection and invocation of [`SourceHealthRepositoryProtocol`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/storage/protocols.py#L138-L167).
- **Proof & Rationale:**
  - Individual zombie instances (`ZRss`, `ZWeb`, etc.) are ephemeral workers and must remain completely decoupled from storage.
  - `ZombieSwarm` already manages `start()`, `stop()`, and `aclose()`, making it the natural supervisory owner for startup hydration and shutdown flushing.
  - Updating health state at the `ZombieSwarm` / supervisory callback level ensures zero database knowledge leaks into `ZombieBase` or collector classes.

### 9. How should startup hydration occur?
```text
ZombieSwarm.start()
  │
  ├── 1. Read persisted health:
  │      records = await self.health_repository.get_all_health()
  │
  ├── 2. Hydrate in-memory SourceDescriptors:
  │      For each SourceHealth in records:
  │        desc = self.registry.get_source(health.source_id)
  │        if desc:
  │          desc.consecutive_failures = health.consecutive_failures
  │          desc.last_attempt = health.last_attempt
  │          desc.last_success = health.last_success
  │          desc.cooldown_until = health.cooldown_until
  │          desc.last_working_tier = health.working_bypass_tier
  │          desc.is_blacklisted = (health.status in (DEAD, QUARANTINED))
  │
  └── 3. Instantiate and start hunting tasks with hydrated cooldown timers.
```

### 10. How should shutdown flush pending health state?
- In `ZombieSwarm.stop()` / `ZombieSwarm.aclose()`:
  - Cancel all active hunting tasks.
  - Export current `SourceHealth` models for all registered sources and execute an atomic batch persist: `await self.health_repository.save_health_batch(all_health)`.
  - Ensures clean state preservation during application teardown.

### 11. How can health persistence remain independent of SQLite?
- `ZombieSwarm` accepts `Optional[SourceHealthRepositoryProtocol]`.
- All interactions use protocol methods: `await self.health_repository.get_all_health()`, `await self.health_repository.save_health(...)`, and `await self.health_repository.save_health_batch(...)`.
- Zero direct references to `SqliteSourceHealthRepository`, `SqliteEngine`, `aiosqlite`, or `sqlite3`.

### 12. How can Phase 4 zombie acquisition remain storage-agnostic?
- `ZombieBase` and individual zombie classes (`ZRss`, `ZWeb`, `ZCorp`, `ZHacker`, `ZGitHub`, `ZSecurity`) do not import or call any repository.
- They interact only with `SourceDescriptor` and return pure `List[SourceObservation]` domain models.

### 13. How can SourceRegistry participate without becoming a storage layer?
- `SourceRegistry` maintains its role as the configuration and probing authority.
- `SourceRegistry` provides helper methods to convert `SourceDescriptor` $\longleftrightarrow$ `SourceHealth` without performing database I/O itself.

### 14. What is the minimum set of files that must change?
1. [`src/zombies/swarm.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/swarm.py): Add `health_repository` injection, startup hydration, hunt outcome tracking, and graceful shutdown flushing.
2. [`src/engine/source_registry.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/source_registry.py): Add `to_source_health()` and `apply_source_health()` helpers on `SourceDescriptor`.
3. [`src/engine/unified_chain.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/unified_chain.py): Pass `health_repository` during `UnifiedFeedChainEngine` initialization if configured.
4. [`tests/test_source_health_lifecycle.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/tests/test_source_health_lifecycle.py): Comprehensive unit and integration test suite.

---

## 3. Component Architecture & Data Flow

### A. Runtime Hunt Outcome Tracking
```text
Zombie.start_hunting()
  │
  ├── Try:
  │     new_sources = await self.hunt()
  │     Outcome: SUCCESS (status_code=200, count=len(new_sources))
  │
  └── Except Exception as e:
        Outcome: FAILURE (status_code=getattr(e, 'status', None), error=str(e))
        │
        ▼
Swarm / Supervisor records outcome:
  health = desc.to_source_health()
  if success:
      health.record_success(working_tier)
  else:
      health.record_failure(status_code, retry_after)
  desc.apply_source_health(health)
  await health_repository.save_health(health)
```

### B. Dependency Graph & Layer Invariants
```text
[Domain Layer]
  src/domain/models.py (SourceHealth, SourceObservation)
  src/domain/enums.py (SourceHealthStatus, ZombieSpecies, SourceTier)
       ▲
       │
[Storage Layer]
  src/storage/protocols.py (SourceHealthRepositoryProtocol)
  src/storage/sqlite_source_health_repository.py (SqliteSourceHealthRepository)
       ▲
       │ (Depends only on Protocol)
[Acquisition Layer]
  src/zombies/swarm.py (ZombieSwarm)
  src/engine/source_registry.py (SourceRegistry)
       ▲
       │
  src/engine/unified_chain.py (UnifiedFeedChainEngine)
```

---

## 4. Scope & Boundary Rules

### Files Proposed for Modification in 5E-D:
- `src/zombies/swarm.py`
- `src/engine/source_registry.py`
- `src/engine/unified_chain.py`
- `tests/test_source_health_lifecycle.py` (New test file)
- `PHASE_5E_D_IMPLEMENTATION_REPORT.md` (New closeout report)

### Files Explicitly FORBIDDEN from Modification:
- `src/domain/models.py` (Domain models frozen)
- `src/domain/enums.py` (Domain enums frozen)
- `src/storage/schema_sqlite.sql` (Storage DDL frozen)
- `src/storage/sqlite_source_health_repository.py` (Repository frozen)
- `src/storage/sqlite_article_repository.py` (Repository frozen)
- `src/storage/sqlite_event_repository.py` (Repository frozen)
- `src/pipeline/*` (Pipeline frozen)
- `src/api/*` (Deferred to 5E-E)
- `src/database.py`, `src/db_storage/`, `src/events/` (Legacy storage deferred to 5F)

---

## 5. Test Strategy for Subphase 5E-D

The test suite in `tests/test_source_health_lifecycle.py` must verify:
1. **Startup Hydration:** `ZombieSwarm.hydrate_health()` restores cooldowns and failure counts from repository before hunting starts.
2. **Success State Recording:** Successful hunt updates `SourceHealth` to `HEALTHY` and resets consecutive failures.
3. **Failure State Recording:** Exceptions or failed fetches trigger `record_failure()` and persist `DEGRADED` / `COOLDOWN`.
4. **Rate Limit Recovery:** HTTP 429 backoff is recorded, persisted, and hydrated across restarts.
5. **Quarantine Enforcement:** HTTP 404/410 puts source into 7-day quarantine.
6. **Graceful Shutdown Flush:** `ZombieSwarm.aclose()` / `stop()` flushes current health states atomically.
7. **Zero-Repository Fallback:** `ZombieSwarm` operates seamlessly when `health_repository` is `None`.
8. **AST Boundary Check:** `src/zombies/` contains zero direct imports of SQLite or database implementations.

---

## 6. Acceptance Criteria for Subphase 5E-D

1. **Protocol Dependency Only:** `ZombieSwarm` imports only `SourceHealthRepositoryProtocol`.
2. **Durable Operational Resilience:** Quarantines and cooldowns survive process restarts.
3. **Zero Zombie Worker Pollution:** `ZombieBase` and individual zombie classes remain pure and storage-free.
4. **Full Regression Health:** All 315 existing tests continue passing without regression.
5. **Zero GitHub Pushes / Clean Tree:** No unauthorized commits or pushes.

---

**Architecture Review Complete.** Ready to proceed with gated implementation upon your direction.
