# Compatibility Layer & Resilience Ecosystem Inventory

**Document Status**: Phase 0 Baseline  
**Policy**: Compatibility shims are temporary migration mechanisms with explicit retirement milestones, never permanent architecture.

---

## 1. Compatibility Modules (`src/compatibility/`)

### 1.1 `src/compatibility/package_shim.py` (310 lines)
- **Purpose**: Dynamic module import redirector. Intercepts calls to old module paths (e.g., `src.scraper`, `src.database`) and redirects them to newer package locations.
- **Current Consumers**: Used in legacy test cases and unmigrated GUI panels.
- **Replacement**: Update all import statements across `src/`, `gui_qt/`, and `tests/` to use canonical direct imports.
- **Retirement Milestone**: Phase 8 (Delete).

---

### 1.2 `src/compatibility/rss_adapter.py` (320 lines)
- **Purpose**: Normalizes legacy RSS/Atom dictionary formats into modern dataclass instances.
- **Current Consumers**: `EnhancedNewsPipeline`, `DiscoveryAggregator`.
- **Replacement**: Merge format handling directly into `src/zombies/z_rss.py`.
- **Retirement Milestone**: Phase 8 (Merge & Delete).

---

## 2. Resilience Modules (`src/resilience/`)

### 2.1 `src/resilience/source_health.py` (210 lines)
- **Purpose**: Tracks success/failure metrics per news source.
- **Current State**: Rudimentary counters.
- **Target State**: **KEEP & UPGRADE**. Transform into a formal state machine:
  `HEALTHY` ➔ `DEGRADED` ➔ `RATE_LIMITED` ➔ `COOLDOWN` ➔ `RECOVERING` (and terminal `DISABLED`).

---

### 2.2 `src/resilience/deprecation_manager.py` (160 lines)
- **Purpose**: Emits structured warnings when deprecated code paths or legacy functions are invoked.
- **Verdict**: **KEEP**. Use during Phases 1–8 to alert operators of any remaining legacy calls before deletion.

---

### 2.3 `src/resilience/auto_fixer.py` (410 lines)
- **Purpose**: Attempts runtime monkey-patching of failed connections and corrupted data structures.
- **Problem**: Violates the non-negotiable engineering principle: *No silent fallbacks / fail explicitly*. Masking errors prevents genuine root-cause resolution.
- **Verdict**: **DELETE** in Phase 8.

---

### 2.4 `src/resilience/warning_orchestrator.py` (180 lines)
- **Purpose**: Collects and suppresses runtime warnings.
- **Verdict**: **DELETE** in Phase 8. Standard Python `logging` and `warnings` configurations in `pyproject.toml` provide cleaner, standard suppression.
