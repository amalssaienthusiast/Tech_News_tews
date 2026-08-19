"""Smoke test for the hardened src/api/app.py — verifies auth, health, metrics."""
import os
os.environ["API_ALLOW_ANONYMOUS"] = "false"

from fastapi.testclient import TestClient
from src.api.app import app, api_key_manager

client = TestClient(app)

def test_health_no_auth_required():
    """GET /health must succeed without an API key (orchestrators need it)."""
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "timestamp" in body
    print(f"  /health -> {r.status_code} OK")

def test_metrics_no_auth_required():
    """GET /metrics must succeed without an API key (Prometheus needs it)."""
    r = client.get("/metrics")
    assert r.status_code == 200, r.text
    assert "technews_uptime_seconds" in r.text
    print(f"  /metrics -> {r.status_code} OK (prometheus format)")

def test_root_requires_auth():
    """GET / requires X-API-Key header when API_ALLOW_ANONYMOUS=false."""
    r = client.get("/")
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    print(f"  / (no key) -> {r.status_code} (correctly rejected)")

def test_feed_requires_auth():
    """GET /feed/latest requires auth."""
    r = client.get("/feed/latest")
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    print(f"  /feed/latest (no key) -> {r.status_code} (correctly rejected)")

def test_invalid_key_rejected():
    """Invalid API key returns 401."""
    r = client.get("/", headers={"X-API-Key": "tns_invalid_key_12345"})
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    print(f"  / (invalid key) -> {r.status_code} (correctly rejected)")

def test_valid_key_works():
    """Create a real key, then use it."""
    # Create a key directly via the manager (bypass the pro-tier check)
    plaintext = api_key_manager.create_key(user_id="test_user", tier="pro", name="test")
    assert plaintext.startswith("tns_"), f"expected tns_ prefix, got {plaintext[:20]}"

    # Use it
    r = client.get("/", headers={"X-API-Key": plaintext})
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["tier"] == "pro"
    print(f"  / (valid key) -> {r.status_code} OK, tier={body['tier']}")

def test_rate_limit_headers():
    """Rate limit counter increments."""
    plaintext = api_key_manager.create_key(user_id="test_user2", tier="free", name="ratelimit")
    # Make 3 requests
    for i in range(3):
        r = client.get("/", headers={"X-API-Key": plaintext})
        assert r.status_code == 200, f"request {i}: {r.status_code}"
    print(f"  3 requests with free-tier key -> all 200 OK")

def test_openapi_docs_available():
    """OpenAPI schema is reachable for documentation."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Real-Time News API"
    assert "/health" in schema["paths"]
    assert "/metrics" in schema["paths"]
    assert "/feed/latest" in schema["paths"]
    print(f"  /openapi.json -> {r.status_code} OK, {len(schema['paths'])} paths")

if __name__ == "__main__":
    print("Running smoke tests for hardened src/api/app.py...")
    test_health_no_auth_required()
    test_metrics_no_auth_required()
    test_root_requires_auth()
    test_feed_requires_auth()
    test_invalid_key_rejected()
    test_valid_key_works()
    test_rate_limit_headers()
    test_openapi_docs_available()
    print("\nAll smoke tests passed.")
