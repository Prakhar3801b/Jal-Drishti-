"""
JalDrishti API Gateway — Test Script

Run this from the project root while the backend is running on localhost:8000.

Usage:
    python test_gateway_api.py

This script tests the full lifecycle of the API gateway:
  1. Admin login (to get a JWT token)
  2. Create an API key via the gateway admin endpoint
  3. List keys
  4. Use the API key to hit external data endpoints
  5. Check rate-limit headers
  6. View usage analytics
  7. Revoke the key
  8. Confirm revoked key is rejected
"""

from __future__ import annotations

import json
import sys
import time

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

BASE = "http://localhost:8000"

# ANSI colours for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed = 0
failed = 0


def header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")


def step(name: str) -> None:
    print(f"\n{BOLD}> {name}{RESET}")


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  {GREEN}[PASS] {msg}{RESET}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  {RED}[FAIL] {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}[WARN] {msg}{RESET}")


def info(msg: str) -> None:
    print(f"  {msg}")


# ─────────────────────────────────────── 0. Check backend is up
header("JalDrishti API Gateway — Integration Tests")

step("Checking backend health")
try:
    r = requests.get(f"{BASE}/api/health", timeout=5)
    if r.status_code == 200:
        ok(f"Backend is up: {r.json().get('status', '?')}")
    else:
        fail(f"Backend returned {r.status_code}")
        sys.exit(1)
except requests.ConnectionError:
    fail("Cannot reach backend at localhost:8000. Is it running?")
    print(f"\n  Start it with:  cd backend && python -m uvicorn app.main:app --port 8000\n")
    sys.exit(1)

# ─────────────────────────────────────── 0b. Gateway health
step("Checking gateway health")
r = requests.get(f"{BASE}/api/gateway/health", timeout=5)
if r.status_code == 200:
    data = r.json()
    ok(f"Gateway up — scopes: {data.get('scopes')}, tiers: {data.get('tiers')}")
else:
    fail(f"Gateway health returned {r.status_code}: {r.text}")
    sys.exit(1)


# ─────────────────────────────────────── 1. Admin login
header("Step 1 — Admin Login")

step("Logging in as 'central' (demo mode)")
r = requests.post(f"{BASE}/api/auth/demo", json={"role": "central", "state": None, "district": None}, timeout=5)
if r.status_code == 200:
    login_data = r.json()
    admin_token = login_data.get("token")
    if admin_token:
        ok(f"Logged in as: {login_data['user']['username']} ({login_data['user']['role']})")
    else:
        fail("No token in login response")
        sys.exit(1)
else:
    fail(f"Login failed: {r.status_code} {r.text}")
    sys.exit(1)

admin_headers = {"Authorization": f"Bearer {admin_token}"}


# ─────────────────────────────────────── 2. Create an API key
header("Step 2 — Create API Key")

step("Creating a test API key")
create_body = {
    "name": "Integration Test Key",
    "environment": "test",
    "tier": "standard",
    "scopes": ["score_read", "forecast_read", "alert_subscribe"],
}
r = requests.post(f"{BASE}/api/gateway/admin/keys", json=create_body, headers=admin_headers, timeout=5)
if r.status_code == 201:
    key_data = r.json()
    api_key = key_data.get("key")
    key_id = key_data.get("id")
    ok(f"Key created: id={key_id}, prefix={key_data.get('key_prefix')}")
    ok(f"Environment: {key_data.get('environment')}, Tier: {key_data.get('tier')}")
    ok(f"Scopes: {key_data.get('scopes')}")
    info(f"  Full key (shown once): {api_key[:20]}...")
else:
    fail(f"Create failed: {r.status_code} {r.text}")
    sys.exit(1)


# ─────────────────────────────────────── 3. List keys
header("Step 3 — List API Keys")

step("Listing all active keys")
r = requests.get(f"{BASE}/api/gateway/admin/keys", headers=admin_headers, timeout=5)
if r.status_code == 200:
    data = r.json()
    ok(f"Found {len(data['keys'])} active key(s)")
    for k in data["keys"]:
        info(f"  • {k['name']} ({k['key_prefix']}) — {k['tier']}, {'active' if k['is_active'] else 'revoked'}")
else:
    fail(f"List failed: {r.status_code}")


# ─────────────────────────────────────── 4. Use the API key on external endpoints
header("Step 4 — External Data Endpoints")
api_headers = {"Authorization": f"Bearer {api_key}"}

# 4a. Country summary (score_read)
step("GET /api/gateway/v1/scores/summary (scope: score_read)")
r = requests.get(f"{BASE}/api/gateway/v1/scores/summary", headers=api_headers, timeout=10)
if r.status_code == 200:
    data = r.json()
    ok(f"Country summary: run_id={data.get('run_id')}, {data.get('locations')} locations")
    rl_limit = r.headers.get("X-RateLimit-Limit")
    rl_remaining = r.headers.get("X-RateLimit-Remaining")
    if rl_limit:
        ok(f"Rate-limit headers: limit={rl_limit}, remaining={rl_remaining}")
    else:
        warn("No rate-limit headers in response")
elif r.status_code == 503:
    warn(f"Engine still initialising (503) — this is expected on a cold start")
else:
    fail(f"scores/summary: {r.status_code} {r.text}")

# 4b. All locations (score_read)
step("GET /api/gateway/v1/scores/locations (scope: score_read)")
r = requests.get(f"{BASE}/api/gateway/v1/scores/locations", headers=api_headers, timeout=10)
if r.status_code == 200:
    data = r.json()
    ok(f"Locations: {len(data.get('locations', []))} items")
elif r.status_code == 503:
    warn("Engine still initialising (503)")
else:
    fail(f"scores/locations: {r.status_code}")

# 4c. Alerts (alert_subscribe)
step("GET /api/gateway/v1/alerts (scope: alert_subscribe)")
r = requests.get(f"{BASE}/api/gateway/v1/alerts", headers=api_headers, timeout=10)
if r.status_code == 200:
    data = r.json()
    ok(f"Alerts: {len(data.get('alerts', []))} items")
elif r.status_code == 503:
    warn("Engine still initialising (503)")
else:
    fail(f"alerts: {r.status_code}")

# 4d. Gauges (alert_subscribe)
step("GET /api/gateway/v1/alerts/gauges (scope: alert_subscribe)")
r = requests.get(f"{BASE}/api/gateway/v1/alerts/gauges", headers=api_headers, timeout=10)
if r.status_code == 200:
    data = r.json()
    ok(f"Gauge stations: {len(data.get('stations', []))} items")
elif r.status_code == 503:
    warn("Engine still initialising (503)")
else:
    fail(f"alerts/gauges: {r.status_code}")

# 4e. Scope check — rivers should be FORBIDDEN (maps_read not in our scopes)
step("GET /api/gateway/v1/rivers (scope: maps_read — NOT in our key)")
r = requests.get(f"{BASE}/api/gateway/v1/rivers", headers=api_headers, timeout=10)
if r.status_code == 403:
    ok(f"Correctly denied: {r.json().get('detail')}")
else:
    fail(f"Expected 403, got {r.status_code}")

# 4f. No auth header → 401
step("GET /api/gateway/v1/scores/summary (no auth header)")
r = requests.get(f"{BASE}/api/gateway/v1/scores/summary", timeout=5)
if r.status_code == 401:
    ok(f"Correctly rejected unauthenticated request: {r.json().get('detail')}")
else:
    fail(f"Expected 401, got {r.status_code}")

# 4g. Bad key → 401
step("GET /api/gateway/v1/scores/summary (invalid key)")
r = requests.get(f"{BASE}/api/gateway/v1/scores/summary", headers={"Authorization": "Bearer sk_test_invalid"}, timeout=5)
if r.status_code == 401:
    ok(f"Correctly rejected invalid key: {r.json().get('detail')}")
else:
    fail(f"Expected 401, got {r.status_code}")


# ─────────────────────────────────────── 5. Usage analytics
header("Step 5 — Usage Analytics")

step(f"GET /api/gateway/admin/keys/{key_id}/usage")
r = requests.get(f"{BASE}/api/gateway/admin/keys/{key_id}/usage?hours=1", headers=admin_headers, timeout=5)
if r.status_code == 200:
    data = r.json()
    ok(f"Total requests in window: {data.get('total_requests')}")
    ok(f"Current window count: {data.get('current_window_count')}")
    for ep in data.get("by_endpoint", []):
        info(f"  {ep['method']} {ep['endpoint']}: {ep['count']}")
else:
    fail(f"Usage: {r.status_code}")

step("GET /api/gateway/admin/overview")
r = requests.get(f"{BASE}/api/gateway/admin/overview", headers=admin_headers, timeout=5)
if r.status_code == 200:
    data = r.json()
    ok(f"Overview: {data['keys']['active']} active, {data['requests']['today']} requests today")
else:
    fail(f"Overview: {r.status_code}")


# ─────────────────────────────────────── 6. Revoke the key
header("Step 6 — Revoke Key")

step(f"DELETE /api/gateway/admin/keys/{key_id}")
r = requests.delete(f"{BASE}/api/gateway/admin/keys/{key_id}", headers=admin_headers, timeout=5)
if r.status_code == 200:
    ok(f"Key revoked: {r.json()}")
else:
    fail(f"Revoke: {r.status_code}")

# Confirm the revoked key is rejected
step("Using revoked key → should be 401")
r = requests.get(f"{BASE}/api/gateway/v1/scores/summary", headers=api_headers, timeout=5)
if r.status_code == 401:
    ok(f"Revoked key correctly rejected: {r.json().get('detail')}")
else:
    fail(f"Expected 401 after revocation, got {r.status_code}")


# ─────────────────────────────────────── Summary
header("Test Summary")
total = passed + failed
print(f"\n  {GREEN}{passed} passed{RESET}  {RED}{failed} failed{RESET}  out of {total} checks\n")
if failed:
    print(f"  {RED}{BOLD}Some tests failed.{RESET}")
    sys.exit(1)
else:
    print(f"  {GREEN}{BOLD}All tests passed! [OK]{RESET}")
    sys.exit(0)
