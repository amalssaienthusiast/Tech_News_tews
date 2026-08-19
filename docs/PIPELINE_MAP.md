# Pipeline Map & Data Flow Architecture

**Document Status**: Phase 0 Baseline  
**Scope**: Ingestion pipelines, clustering, enrichment, deduplication, and publication data flows.

---

## 1. Existing Competing Pipelines (The Dual-Generation Problem)

The repository currently runs **multiple overlapping generations of ingestion and processing logic** simultaneously:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CURRENT FRAGMENTED STATE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [Zombie Swarm] ───► [Event Brain] ───► EventClusterer ──► ConfidenceEngine │
│        │                                                    │               │
│        ▼                                                    ▼               │
│  [Legacy Feed Chain] ──► DedupGate ──► QualityGate ──► ContentEnhancer      │
│        ▲                                                    │               │
│        │                                                    ▼               │
│  [Discovery Pipeline] ──► API Sources ──────────────► RingBuffer / API      │
│        ▲                                                    │               │
│        │                                                    ▼               │
│  [Breaking Scanner] ──► FreshnessGate ─────────────► SSE / Telegram        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Pipeline Comparison

| Pipeline | Entry Class / File | Ingestion Sources | Deduplication Mechanism | Freshness Evaluation | Delivery Mechanism |
|:---|:---|:---|:---|:---|:---|
| **Pipeline 1: Event Brain** | `UnifiedFeedChainEngine._on_zombie_found_source` | `ZombieSwarm` (RSS, GitHub, HackerNews, Web, Security) | Stage 1 URL MD5 index in `EventClusterer` | `FreshnessGate` scoring (`FreshnessLevel`) | Dynamic event update via `broadcast_event_update` |
| **Pipeline 2: Legacy Feed Chain** | `FeedChain`, `EnhancedNewsPipeline` | `SourceRegistry` scheduled items | `DedupGate` (Canonical URL + MinHash shingle Jaccard) | `SourceQualityFilter` 72-hr window | `FeedChain` subscriber callback -> `ArticleRingBuffer` |
| **Pipeline 3: Breaking News Scanner** | `BreakingNewsScanner` (`src/engine/breaking_news_pipeline.py`) | Cyclic scanner polling priority sources | Shared `DedupGate` instance | `FreshnessGate` (30m hard / 60m soft cutoff) | High-priority SSE broadcast (`event: breaking`) |
| **Pipeline 4: Discovery Aggregator** | `DiscoveryAggregator` (`src/discovery.py`) | Google News RSS, Bing News, NewsAPI | None at discovery stage; relies on downstream `DedupGate` | Query-time parameters (e.g. `when:1d`) | Batched lists returned to `EnhancedNewsPipeline` |
| **Pipeline 5: Deep Realtime Feeder** | `RealtimeNewsFeeder` (`src/engine/realtime_feeder.py`) | Raw URL lists and directory scrapers | Memory seen set | Regex date parser | Database insert (`DatabaseHandler`) |

---

## 3. Critical Flow Conflicts

1. **Double Gate Execution**: When a zombie discovers a source, `unified_chain.py` routes the observation into `EventClusterer` (Pipeline 1) AND simultaneously transforms it into a legacy `Article` and pushes it into `DedupGate` + `QualityGate` + `ContentEnhancer` (Pipeline 2).
2. **Dedup Poisoning**: In Pipeline 2, `dedup_gate.py` permanently indexes candidates before `quality_gate.py` runs. A low-quality article rejected by the quality gate prevents any subsequent high-quality revision of the same URL from ever being accepted.
3. **Freshness Discrepancy**: Pipeline 3 enforces strict ≤30min breaking news cutoffs, while Pipeline 2 accepts articles up to 72 hours old or undated articles without distinguishing their freshness tier.

---

## 4. Target Canonical Ingestion Architecture

All ingestion sources (Zombies, Discovery Adapters, Webhooks) will converge to **exactly one canonical ingestion graph**:

```text
                     SOURCE ADAPTERS & ZOMBIES
     [RSS Zombie]  [GitHub Zombie]  [Hacker Zombie]  [Web Zombie]
                           │
                           ▼
                   SourceObservation
               (url, title, raw_text, source,
                discovered_at, source_tier)
                           │
                           ▼
                    1. Normalizer
             (URL canonicalization, tracking
              stripping, Unicode normalization)
                           │
                           ▼
                   2. Freshness Gate
             (Extract published_at, updated_at;
              Classify F0..F5 / STALE / UNKNOWN;
              Reject STALE / unverified UNKNOWN)
                           │
                           ▼
                3. Technology Relevance
             (Multi-domain tech scoring, entity
              prior, explainable reject reasons)
                           │
                           ▼
                    4. Quality Gate
             (Spam detection, headline length,
              readability, boilerplate filter)
                           │
                           ▼
                 5. Deduplication Gate
             (URL bloom / exact check -> Candidate;
              *Commit ACCEPTED only after quality pass*)
                           │
                           ▼
                  6. Event Clusterer
             (Deterministic entity overlap +
              ordered bigram lexical matching ->
              Cluster into single multi-source Event)
                           │
                           ▼
              7. Confidence & Importance
             (Cross-source corroboration, primary
              source boost -> breaking_score)
                           │
                           ▼
               8. Content Enrichment (Async)
             (Structured AI summary, key takeaways,
              bounded worker pool & circuit breaker)
                           │
                           ▼
                  9. Persistence Store
             (Durable non-blocking write to
              PostgreSQL / Async SQLite)
                           │
                           ▼
                 10. Publication Bus
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
        SSE Stream    Telegram Bot   FastAPI / WS
       (/api/v1/stream) (@tewsavailable) (/feed/latest)
```
