# Acquisition Network Security Map

**Authoritative Outbound Network Boundary & Call Graph**  
**Phase**: Phase 8 Engineering Hardening — Gate 8E-H2  
**Status**: 🟢 AUTHORITATIVE & EXHAUSTIVE  
**Date**: `2026-08-17`  

---

## 1. Outbound Network Call Graph & Boundary Inventory

Every production outbound network call site across the repository is inventoried below, tracing the path from high-level caller through intermediate helpers to the underlying network transport socket.

```text
                               ┌──────────────────────────────────────────────┐
                               │           PRODUCTION ACQUISITION             │
                               │  (Zombie Swarm / Discovery / Bypass Ladder)  │
                               └──────────────────────┬───────────────────────┘
                                                      │
                                                      ▼
                               ┌──────────────────────────────────────────────┐
                               │     CENTRAL ACQUISITION SECURITY GATEWAY     │
                               │       (src/security/acquisition_policy.py)   │
                               │       (src/security/ssrf_guard.py)           │
                               │                                              │
                               │  1. Scheme & Syntax Validation               │
                               │  2. DNS Resolution & Private IP Rejection   │
                               │  3. Multi-Hop Redirect Validation            │
                               │  4. Robots.txt Compliance Policy             │
                               │  5. TLS Strict Verification (Default-ON)     │
                               │  6. Streaming Payload & Decompression Limits │
                               │  7. Connection & Per-Host Rate Limits        │
                               └──────────────────────┬───────────────────────┘
                                                      │
                         ┌────────────────────────────┼────────────────────────────┐
                         ▼                            ▼                            ▼
          ┌─────────────────────────────┐┌─────────────────────────────┐┌─────────────────────────────┐
          │     SafeHttpClient (HTTP)   ││     Primp / Curl Impersonate││     Stealth Playwright      │
          │    (aiohttp with SSRFGuard) ││    (Client-side SSRF Pre-Chk││  (URL Validated + Isolated) │
          └─────────────────────────────┘└─────────────────────────────┘└─────────────────────────────┘
```

---

## 2. Exhaustive Outbound Network Call Site Matrix

| Call Site | Module / Path | Protocol | Caller | Production Reachable? | Security Guard | Robots | TLS Enforced | Redirect Validated | Classification |
|---|---|---|---|---|---|---|---|---|---|
| **CS-01** | [`src/bypass/bypass_resolver.py:121`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/bypass_resolver.py#L121) | HTTP / HTTPS (aiohttp) | `InternetBrowser.fetch()` $\to$ `ZRss`, `ZWeb`, `ZCorp`, `ZSecurity` | **Yes (Canonical)** | `SSRFGuard` / `SafeHttpClient` | Via Acquisition Policy | Yes (Default-ON) | Per-Hop SSRF Validated | 🟢 **CANONICAL** |
| **CS-02** | [`src/bypass/bypass_resolver.py:135`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/bypass_resolver.py#L135) | HTTP / HTTPS (primp) | `InternetBrowser.fetch()` (Tier 1 Impersonation) | **Yes (Canonical)** | Pre-flight `SSRFGuard.validate_url()` | Via Acquisition Policy | Yes (Default-ON) | Pre-validated + Non-private target | 🟢 **CANONICAL** |
| **CS-03** | [`src/bypass/bypass_resolver.py:149`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/bypass_resolver.py#L149) | Chromium (Playwright `page.goto`) | `StealthBrowser.fetch_with_bypass()` (Tier 2 Browser) | **Yes (Canonical)** | Pre-flight `SSRFGuard.validate_url()` | Via Acquisition Policy | Yes (Browser WebPKI) | Initial URL SSRF-checked | 🟢 **CANONICAL** |
| **CS-04** | [`src/bypass/bypass_resolver.py:168`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/bypass_resolver.py#L168) | Chromium via Proxy | `SmartProxyRouter` + `StealthBrowser` (Tier 3 Proxy) | **Yes (Canonical)** | Pre-flight `SSRFGuard.validate_url()` | Via Acquisition Policy | Yes (Browser WebPKI) | Initial URL SSRF-checked | 🟢 **CANONICAL** |
| **CS-05** | [`src/bypass/bypass_resolver.py:183`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/bypass/bypass_resolver.py#L183) | HTTPS (Wayback / Archive) | `PaywallBypass.bypass_paywall()` (Tier 4 Archive) | **Yes (Canonical)** | Pre-flight `SSRFGuard.validate_url()` | N/A (Archive fallback) | Yes (Default-ON) | Per-Hop SSRF Validated | 🟢 **CANONICAL** |
| **CS-06** | [`src/zombies/z_github.py:120`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/z_github.py#L120) | HTTPS (GitHub REST/GraphQL API) | `ZGitHub.hunt()` | **Yes (Canonical)** | Pre-flight `SSRFGuard.validate_url()` (`api.github.com`) | API TOS Compliant | Yes (Default-ON) | No redirects needed | 🟢 **CANONICAL** |
| **CS-07** | [`src/zombies/z_hacker.py:59`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/zombies/z_hacker.py#L59) | HTTPS (Firebase REST API) | `ZHacker.hunt()` | **Yes (Canonical)** | Pre-flight `SSRFGuard.validate_url()` (`firebaseio.com`) | API TOS Compliant | Yes (Default-ON) | No redirects needed | 🟢 **CANONICAL** |
| **CS-08** | [`src/discovery/lifecycle.py:180`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/discovery/lifecycle.py#L180) | HTTP / HTTPS (Discovery Fetch) | `DiscoveryLifecycleManager.discover_new_sources()` | **Yes (Canonical)** | `SSRFGuard.validate_url()` + `SafeHttpClient` | Enforced | Yes (Default-ON) | Per-Hop SSRF Validated | 🟢 **CANONICAL** |
| **CS-09** | [`src/discovery/global_discovery.py:140`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/discovery/global_discovery.py#L140) | HTTPS (DDG / Bing / Google Search) | `GlobalSourceDiscoveryEngine.discover()` | **Yes (Canonical)** | `SSRFGuard.validate_url()` | Search API Politeness | Yes (Default-ON) | Strict validation | 🟢 **CANONICAL** |
| **CS-10** | [`src/utils/thumbnail.py:78`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/utils/thumbnail.py#L78) | HTTP / HTTPS (aiohttp) | `ThumbnailDownloader.download()` | **Yes (Utility)** | `SSRFGuard.validate_url()` + `SafeHttpClient` | N/A (Image CDN) | Yes (Strict WebPKI) | Per-Hop SSRF Validated | 🟢 **CANONICAL** |
| **CS-11** | [`src/crawler/enhanced_crawler.py:348`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/crawler/enhanced_crawler.py#L348) | HTTP / HTTPS (aiohttp) | `EnhancedCrawler.crawl()` | Optional Utility | `SSRFGuard.validate_url()` | Enforced via `robots.txt` | Yes (Default-ON) | Validated | 🔵 **UTILITY** |
| **CS-12** | [`src/crawler/enhanced_crawler.py:440`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/crawler/enhanced_crawler.py#L440) | HTTP / HTTPS (`RobotFileParser.read`) | `EnhancedCrawler._check_robots()` | Optional Utility | Guarded with `SSRFGuard.validate_url(robots_url)` | Self (robots.txt parser)| Yes (Default-ON) | Validated | 🔵 **UTILITY** |
| **CS-13** | [`src/crawler/enhanced_crawler.py:542`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/crawler/enhanced_crawler.py#L542) | Chromium (`page.goto`) | `EnhancedCrawler._render_js()` | Optional Utility | Pre-flight `SSRFGuard.validate_url()` | Respects robots | Yes (Browser WebPKI) | Validated | 🔵 **UTILITY** |
| **CS-14** | [`src/sources/duckduckgo_search.py:219`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/sources/duckduckgo_search.py#L219) | HTTPS (DDGS client) | `DuckDuckGoSearch.search()` | Optional Source | Host pinned to DuckDuckGo endpoints | Respects rate limits | Yes (Default-ON) | Validated | 🔵 **SOURCE** |
| **CS-15** | [`src/sources/google_news.py:164`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/sources/google_news.py#L164) | HTTPS (Google News RSS) | `GoogleNewsScraper.fetch()` | Optional Source | Pre-flight `SSRFGuard.validate_url()` | Public RSS Feed | Yes (Default-ON) | Validated | 🔵 **SOURCE** |
| **CS-16** | [`src/sources/reddit_client.py:95`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/sources/reddit_client.py#L95) | HTTPS (Reddit JSON / OAuth API) | `RedditClient.fetch_subreddit()` | Optional Source | Pinned to `reddit.com` / `oauth.reddit.com` | API TOS Compliant | Yes (Default-ON) | Validated | 🔵 **SOURCE** |
| **CS-17** | [`src/engine/source_registry.py:217`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/source_registry.py#L217) | HTTP / HTTPS (Health Probe) | `SourceRegistry.verify_source_health()` | Admin Utility | `SSRFGuard.validate_url()` | N/A (HEAD probe) | Yes (Default-ON) | Validated | 🔵 **UTILITY** |
| **CS-18** | [`src/engine/realtime_feeder.py:639`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/realtime_feeder.py#L639) | HTTP / HTTPS (requests / curl_cffi) | Legacy Monolith Ingestion | 🔴 **No (Legacy)** | Superseded by `ZombieSwarm` | Legacy | Strict | Legacy | 🔴 **LEGACY** |
| **CS-19** | [`src/engine/deep_scraper.py:822`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/deep_scraper.py#L822) | HTTP / HTTPS (aiohttp) | Legacy Deep Scraper | 🔴 **No (Legacy)** | Superseded by `ZombieSwarm` | Legacy | Strict | Legacy | 🔴 **LEGACY** |
| **CS-20** | [`src/engine/directory_scraper.py:286`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/src/engine/directory_scraper.py#L286) | HTTP / HTTPS (aiohttp) | Legacy Directory Scraper | 🔴 **No (Legacy)** | Superseded by `ZombieSwarm` | Legacy | Strict | Legacy | 🔴 **LEGACY** |
| **CS-21** | [`telegram_feeder_bot.py:150`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/telegram_feeder_bot.py#L150) | HTTPS (Telegram Bot API) | Telegram Notification Bot | External Client | Pinned to `api.telegram.org` | N/A (Bot API) | Yes (Default-ON) | Pinned target | 🔵 **CLIENT** |

---

## 3. Security Boundary Controls & Composition

1. **SSRF Guard (`src/security/ssrf_guard.py`)**:
   - Denies IPv4 private ranges (RFC 1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
   - Denies loopback (`127.0.0.0/8`, `::1/128`).
   - Denies link-local / cloud metadata (`169.254.0.0/16`, `fe80::/10`).
   - Denies CGNAT (`100.64.0.0/10`), documentation (`192.0.2.0/24`), broadcast (`255.255.255.255/32`).
   - Denies IPv6 ULA (`fc00::/7`), IPv4-mapped IPv6 (`::ffff:0:0/96`).
   - Rejects non-HTTP schemes (`file://`, `ftp://`, `gopher://`, `javascript:`, `data:`).
2. **Safe HTTP Client (`src/security/ssrf_guard.py:SafeHttpClient`)**:
   - Handles multi-hop redirects manually (`allow_redirects=False`).
   - Re-evaluates `SSRFGuard.validate_url()` on **every single redirect hop**.
   - Defends against Public $\to$ Private redirect bypass attacks.
   - Enforces streaming payload size cap (`10 MB`) and decompressor inflation cap (`10 MB`).
3. **Acquisition Policy (`src/security/acquisition_policy.py`)**:
   - Centralizes the authoritative fetch contract composing SSRF validation, robots.txt evaluation, TLS verification, timeouts, and rate limits.
