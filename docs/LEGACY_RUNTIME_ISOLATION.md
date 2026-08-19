# Legacy Runtime Isolation & Decommissioning Plan

**Audit & Isolation Matrix for Deprecated Modules**  
**Phase**: Phase 8 Engineering Hardening — Gate 8E-H3  
**Status**: 🟢 ISOLATED & DEPRECATED  
**Date**: `2026-08-17`  

---

## 1. Executive Summary

As part of Phase 8H-H3 runtime consolidation, all legacy entrypoints and competing runtime servers have been formally isolated, warned at runtime with `DeprecationWarning`, and disconnected from production deployment infrastructure (`Dockerfile` and `docker-compose.yml`).

---

## 2. Legacy Module Inventory & Isolation Matrix

| Legacy Path | Original Purpose | Historical Callers | Exposed Network Ports | Production Reachable? | Authoritative Canonical Replacement | Deletion Gate |
|---|---|---|---|---|---|---|
| [`main.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/main.py) | Monolithic aggregator + child API supervisor | Development scripts, older deployment docs | 8000 (if `--with-api`) | **NO** (Excluded from Docker/Compose) | API: `uvicorn src.api.app:app`<br>Worker: `python -m src.worker` | Phase 9 (Post-Soak Clean) |
| [`main_engine.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/main_engine.py) | aiohttp server + in-memory ring buffer | Legacy clients, SSE testing | 8080 (HTTP, SSE) | **NO** (Excluded from Docker/Compose) | API: `src.api.app:app`<br>Worker: `src.worker` | Phase 9 (Post-Soak Clean) |
| [`src/api/main.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/api/main.py) | Prototype FastAPI v1.0 | Early API integration tests | 8000 (if run directly) | **NO** (Excluded from Docker/Compose) | `src.api.app:app` | Phase 9 (Post-Soak Clean) |
| `src/engine/orchestrator.py` | Early feed orchestrator | `src/db_storage/` | None | **NO** | `UnifiedFeedChainEngine` | Phase 9 (Post-Soak Clean) |
| `src/scrapers/factory.py` | Legacy scraper instantiator | `main.py` | None | **NO** | `SourceRegistry` + `ZombieSwarm` | Phase 9 (Post-Soak Clean) |

---

## 3. Production Reachability Guarantees

1. **Dockerfile Enforcement**:
   - `Dockerfile` runtime image entrypoint is strictly pinned to:
     ```dockerfile
     ENTRYPOINT ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
     ```
2. **Docker Compose Enforcement**:
   - `docker-compose.yml` explicitly defines two decoupled services:
     - `api`: `command: ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000"]`
     - `worker`: `command: ["python", "-m", "src.worker", "--concurrency", "2", "--db-path", "/data/canonical_technews.db"]`
3. **Packaging Enforcement**:
   - `pyproject.toml` console scripts map exclusively to canonical entrypoints:
     - `technews-api = "main:run_api"` (points to `src.api.app:app`)
     - `technews-worker = "src.worker:main"`
4. **Runtime Warnings**:
   - Executing `main.py`, `main_engine.py`, or importing `src/api/main.py` emits an immediate Python `DeprecationWarning` and logs a formatted warning message to stdout.
