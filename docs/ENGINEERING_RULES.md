# Engineering Rules — Tech News Scrapper

**Status**: Active — binding on all agents, contributors, and automated processes.  
**Effective**: Phase 1A onward.

---

## Architectural Rules

1. **Domain cannot import API/UI.**  
   Core domain models, types, and business logic must never depend on delivery layers (FastAPI, aiohttp, Telegram, GUI).

2. **Engine cannot import API routes.**  
   Pipeline and orchestration code must not import from `src/api/routes/`. Use event buses or callbacks for cross-layer communication.

3. **Zombies only emit SourceObservation.**  
   All zombie species produce a single canonical output type. No zombie may directly write to the database, publish to Telegram, or call API routes.

4. **Publication occurs only through PublicationBus.**  
   SSE, Telegram, WebSocket, and REST feed delivery subscribe to one canonical publication bus. No module may publish directly to a delivery channel.

5. **No sync database I/O inside async paths.**  
   Any code running on the asyncio event loop must use `aiosqlite`, `asyncpg`, or equivalent non-blocking drivers. Synchronous `sqlite3.connect()` on the event loop is forbidden.

6. **No unbounded in-memory collection.**  
   Every in-memory cache, index, or buffer must have an explicit hard capacity limit and eviction policy.

7. **No broad `except`/`pass`.**  
   Silent exception swallowing is forbidden. Every exception handler must either log, re-raise, or take a specific corrective action.

8. **No secret in source.**  
   API keys, tokens, passwords, and credentials must never appear in source code, documentation, or tracked configuration files. Use environment variables loaded from untracked `.env` files.

9. **No new dependency without justification.**  
   Adding a new third-party package requires documented rationale: what it replaces, why alternatives were insufficient, and what its maintenance/security posture is.

10. **No module may have multiple authoritative owners.**  
    Every production module has exactly one owning subsystem. No file may be simultaneously "part of" two competing packages.

11. **Compatibility layers must have retirement dates.**  
    Shims, adapters, and backward-compatibility wrappers must document their target removal phase. They are temporary migration mechanisms, never permanent architecture.

12. **Every production behavior needs tests.**  
    No production code change is complete without corresponding test coverage. Tests are the executable specification.

---

## Agent Discipline Rules (All Phases)

```
NO INCIDENTAL REFORMATTING
NO RENAMING OUTSIDE SCOPE
NO DEPENDENCY UPGRADES
NO STYLE REWRITE
NO "CLEANUP" OF NEIGHBORING CODE
NO PIPELINE/ARCHITECTURE CHANGES DURING SECURITY WORK
```
