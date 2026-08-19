# Phase 6D Architecture Review: Production Security, Authentication & Rate Limiting

**Program**: Phase 6 — Internet-Scale Acquisition, Search, Security & Production Operations  
**Gate**: Gate 6D-A (Security Architecture Review)  
**Status**: SUBMITTED FOR REVIEW & AUTHORIZATION  
**Baseline Commit**: `caaf7c9` (Phase 6C Frozen)  
**Code Modifications in 6D-A**: 0 (Architecture & Design Review Only)  

---

## 1. Executive Summary & Security Model

Subphase **6D** establishes production-grade defense-in-depth for the Tech News Scrapper platform:
1. **Zero-Trust Role-Based Access Control (RBAC)**: Secure multi-tier API key management with constant-time verification.
2. **Token Bucket Rate Limiting**: Per-client and per-role asynchronous rate limiting with standard RFC compliance (`429 Too Many Requests`, `Retry-After`).
3. **Hardened HTTP Security Headers**: OWASP-compliant response headers across all API and GUI endpoints.
4. **Request Body & Header Bounds**: Strict bounds on inbound HTTP request size and header complexity to prevent DoS attacks.
5. **Security Audit Telemetry**: Structured security event logging without leaking secret material or PII.

```
                           INBOUND HTTP REQUEST
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │ 1. Request Size Bounding     │ (Max 2MB Body, Max 16KB Headers)
                     └──────────────┬───────────────┘
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │ 2. Security Headers Injector │ (CSP, HSTS, X-Content-Type, X-Frame)
                     └──────────────┬───────────────┘
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │ 3. Token Bucket Rate Limiter │ (Role & IP Based, RFC 429 Headers)
                     └──────────────┬───────────────┘
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │ 4. RBAC Key Authentication   │ (Constant-Time HMAC, Multi-Tier Roles)
                     └──────────────┬───────────────┘
                                    │
                                    ▼
                         Canonical API Endpoints
                      (/v1/articles, /v1/events, etc.)
```

---

## 2. Role-Based Access Control (RBAC) Architecture

### 1. Role Definitions
| Role | Permissions | Rate Limit Default | Example Endpoints |
|---|---|---|---|
| `admin` | Full read, write, backfill, maintenance, metrics | 1,000 req/min | All endpoints, `/api/v1/system/*`, `/metrics` |
| `read_write` | Read articles/events, write bookmarks/preferences | 300 req/min | `/api/v1/articles/*`, `/api/v1/events/*`, `/api/v1/user/*` |
| `read_only` | Read articles, search FTS5, read public events | 120 req/min | `GET /api/v1/articles/*`, `GET /api/v1/events/*` |
| `anonymous` | Unauthenticated public access (when enabled) | 30 req/min | `GET /health`, `GET /v1/articles` (heavily throttled) |

### 2. Constant-Time Verification & Secret Safety
- API keys are verified using `hmac.compare_digest` to prevent timing attacks.
- Keys are never logged in plain text. Audit logs record only SHA-256 key fingerprints (`key_hash = sha256(key)[:8]`).
- Supports environment-variable configuration (`TECHNEWS_ADMIN_KEY`, `TECHNEWS_API_KEYS`).

---

## 3. Token Bucket Rate Limiting Architecture

### 1. Algorithm: Asynchronous In-Memory Token Bucket
- **Capacity ($C$)**: Maximum burst allowance.
- **Refill Rate ($r$)**: Tokens added per second.
- **Current Tokens**: $\min(C, \text{prev\_tokens} + \Delta t \times r)$.
- **Thread/Async Safety**: Fine-grained per-bucket `asyncio.Lock` with automatic cleanup of idle client buckets (LRU eviction after 1 hour of inactivity).

### 2. Standardized Headers
When a client exceeds their bucket:
- **HTTP Status**: `429 Too Many Requests`
- **Headers**:
  - `Retry-After`: Integer seconds until next available token.
  - `X-RateLimit-Limit`: Maximum tokens per minute.
  - `X-RateLimit-Remaining`: Current available tokens.
  - `X-RateLimit-Reset`: Unix timestamp when bucket fully refills.

---

## 4. Hardened Security Headers

Every outgoing HTTP response is injected with OWASP-recommended headers:
- `X-Content-Type-Options: nosniff` (prevents MIME type sniffing)
- `X-Frame-Options: DENY` (prevents clickjacking)
- `X-XSS-Protection: 1; mode=block` (legacy XSS filter defense)
- `Referrer-Policy: strict-origin-when-cross-origin` (prevents referrer leakage)
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HSTS)

---

## 5. Request Bounding & DoS Protection

- **Maximum Request Body**: 2 MB (rejects oversized uploads with `413 Payload Too Large`).
- **Maximum Header Size**: 16 KB.
- **Request Timeout**: Per-request processing timeout (30 seconds) preventing slowloris hangs.

---

## 6. Subphase 6D Execution Roadmap

```text
Subphase 6D: Production Security, Authentication & Rate Limiting
├── 6D-A: Architecture Review & Design Approval (Current Gate)
├── 6D-B: Security Middleware Implementation (RBAC, Token Bucket, Headers, Body Bounds)
├── 6D-C: API Security Integration & Role-Guarded Endpoints
├── 6D-D: Security Verification (Timing Attacks, Rate Limit Burst/Drain, Header Audits, Fuzzing)
└── 6D-E: Full Regression, Report & Milestone Commit
```

---

## 7. Gate 6D-A Recommendation

Gate **6D-A** establishes a zero-trust, timing-safe security foundation that hardens the platform for production internet exposure without breaking existing repository contracts.

**Gate 6D-A Status**: **SUBMITTED FOR REVIEW & AUTHORIZATION** ✅  
**Ready for**: **Subphase 6D-B Implementation**.
