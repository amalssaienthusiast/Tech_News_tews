# Operational Runbook: Production Incident Response

## 1. Overview & Triage Protocol

This runbook guides on-call engineers in diagnosing and resolving production alerts for the Tech News Scrapper service.

```
                   INCIDENT TRIAGE DECISION TREE
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
HTTP 5xx / API Down       Queue Backpressure         Database Contention
(Check /health endpoint   (Check metrics:            (Check lock wait times,
 & Uvicorn logs)           queue_depth, drop_rate)    WAL size, busy_timeout)
```

---

## 2. Common Production Incidents & Remediation

### Incident A: Ingestion Queue Backpressure Alert (`technews_queue_backpressure_active == 1.0`)
- **Symptoms**: Queue utilization exceeds 80% (8,000 items), `technews_queue_items_dropped_total` is increasing.
- **Root Cause**: Upstream arrival rate exceeds persistence drain capacity ($\lambda > 138\text{ articles/sec}$).
- **Remediation Steps**:
  1. Inspect source acquisition rates: `curl http://localhost:8000/metrics | grep technews_observation_ingest_total`.
  2. Verify that zombie worker concurrency is properly partitioned across shards.
  3. If burst is transient, the queue will automatically drop below 60% watermark and clear backpressure.
  4. If load is sustained, adjust acquisition interval in source registration:
     `UPDATE canonical_sources SET fetch_interval_seconds = fetch_interval_seconds * 2 WHERE tier = 'TIER_3';`

### Incident B: SQLite Lock Wait Inflation / Elevated Commit Latency
- **Symptoms**: Pipeline Stage S10 latency exceeds $100\text{ ms}$, search queries slow down.
- **Root Cause**: Multiple concurrent processes or worker threads competing for single SQLite write lock.
- **Remediation Steps**:
  1. Ensure only 1 dedicated pipeline runner worker is actively writing to the SQLite database file.
  2. Verify WAL mode is enabled: `sqlite3 /data/canonical_technews.db "PRAGMA journal_mode;"` (must return `wal`).
  3. Force a manual WAL checkpoint:
     `sqlite3 /data/canonical_technews.db "PRAGMA wal_checkpoint(TRUNCATE);"`

### Incident C: High Memory Alarm (> 512 MB RSS)
- **Symptoms**: Container memory approaches 512 MB threshold.
- **Root Cause**: Unbounded queue accumulation or process memory leak.
- **Remediation Steps**:
  1. Inspect Prometheus memory metric: `curl http://localhost:8000/metrics | grep process_resident_memory_bytes`.
  2. Verify queue depth is bounded: `curl http://localhost:8000/metrics | grep technews_queue_depth`.
  3. Trigger container restart via supervisor: `docker restart technews_api`.
