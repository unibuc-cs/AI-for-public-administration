"""JSON-driven test runner for the prototype.

Usage:
  python -m tests.run_json_tests --spec tests/tests.json

Design goals:
- No pytest dependency; runs as a simple script.
- Uses FastAPI TestClient to avoid requiring a running server.
- Supports a small assertion vocabulary that maps well to paper claims.

Test JSON format (per test):
  {
    "id": "T01",
    "name": "...",
    "request": {"method": "GET"|"POST", "path": "/...", "json": {...}, ...},
    "expect": {"status": 200, ...}
  }

Supported expectation keys:
- status: integer
- json_contains: {k:v,...} shallow containment
- json_has_keys: ["a","b"] top-level keys
- json_type: "list" | "dict" | "str"
- json_path_equals: {"a.b.c": value, ...}
- json_path_contains: {"a.b": "substr", ...} (string containment)
- json_path_exists: ["a.b", ...]
- set_cookie_contains: substring that must appear in Set-Cookie header

Request extras:
- auth: {username, password} => performs /login and reuses cookies
- cookies: {name:value}
- headers: {name:value}
- sequence: [{json: {...}}, {json: {...}}] => multiple calls; last response used for assertions

Special token in request JSON:
- "@prev.<field>": replaced with value captured from the previous response JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient

# Import app from main
from main import app  # noqa: E402


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(path)
    return cur


def _type_name(x: Any) -> str:
    if isinstance(x, dict):
        return "dict"
    if isinstance(x, list):
        return "list"
    if isinstance(x, str):
        return "str"
    if x is None:
        return "none"
    return type(x).__name__


@dataclass
class RunContext:
    prev_json: Optional[Dict[str, Any]] = None


def _resolve_refs(payload: Any, ctx: RunContext) -> Any:
    if isinstance(payload, str) and payload.startswith("@prev."):
        if not ctx.prev_json:
            raise ValueError(f"Reference {payload} used but no previous JSON is available")
        ref_path = payload[len("@prev.") :]
        return _get_path(ctx.prev_json, ref_path)
    if isinstance(payload, dict):
        return {k: _resolve_refs(v, ctx) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_resolve_refs(v, ctx) for v in payload]
    return payload


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/login", json={"username": username, "password": password})
    if r.status_code != 200:
        raise RuntimeError(f"Login failed for {username}: HTTP {r.status_code} {r.text}")


def _run_single(client: TestClient, req: Dict[str, Any], ctx: RunContext) -> Any:
    method = req.get("method", "GET").upper()
    path = req["path"]

    headers = req.get("headers") or {}
    cookies = req.get("cookies") or {}

    # Tests must be independent: a session established by an earlier test must not
    # leak into a later one that expects an anonymous caller.
    client.cookies.clear()

    # Optional auth handshake
    if "auth" in req and req["auth"]:
        _login(client, req["auth"]["username"], req["auth"]["password"])

    # Multi-call sequence support
    if "sequence" in req and req["sequence"]:
        last = None
        for step in req["sequence"]:
            body = step.get("json")
            if body is not None:
                body = _resolve_refs(body, ctx)
            if method == "POST":
                last = client.post(path, json=body, headers=headers, cookies=cookies)
            else:
                last = client.get(path, headers=headers, cookies=cookies)
            # update prev_json after each step if JSON
            try:
                ctx.prev_json = last.json()
            except Exception:
                ctx.prev_json = None
        return last

    body = req.get("json")
    if body is not None:
        body = _resolve_refs(body, ctx)

    if method == "POST":
        return client.post(path, json=body, headers=headers, cookies=cookies)
    if method == "GET":
        return client.get(path, headers=headers, cookies=cookies)

    raise ValueError(f"Unsupported method: {method}")


def _assert(resp, expect: Dict[str, Any], ctx: RunContext) -> None:
    if "status" in expect:
        assert resp.status_code == expect["status"], f"expected HTTP {expect['status']}, got {resp.status_code}: {resp.text}"

    set_cookie = resp.headers.get("set-cookie", "")
    if "set_cookie_contains" in expect:
        needle = expect["set_cookie_contains"]
        assert needle in set_cookie, f"expected Set-Cookie to contain {needle!r}, got {set_cookie!r}"

    # JSON-related assertions
    payload = None
    if any(k.startswith("json_") for k in expect.keys()):
        payload = resp.json()
        ctx.prev_json = payload if isinstance(payload, dict) else {"_": payload}

    if "json_type" in expect:
        t = _type_name(payload)
        assert t == expect["json_type"], f"expected json_type {expect['json_type']}, got {t}"

    if "json_has_keys" in expect:
        assert isinstance(payload, dict), f"json_has_keys expects dict, got {_type_name(payload)}"
        for k in expect["json_has_keys"]:
            assert k in payload, f"missing key: {k}"

    if "json_contains" in expect:
        assert isinstance(payload, dict), f"json_contains expects dict, got {_type_name(payload)}"
        for k, v in expect["json_contains"].items():
            assert payload.get(k) == v, f"expected {k}={v!r}, got {payload.get(k)!r}"

    if "json_path_exists" in expect:
        assert isinstance(payload, dict), f"json_path_exists expects dict, got {_type_name(payload)}"
        for p in expect["json_path_exists"]:
            _get_path(payload, p)  # will raise if missing

    if "json_path_equals" in expect:
        assert isinstance(payload, dict), f"json_path_equals expects dict, got {_type_name(payload)}"
        for p, v in expect["json_path_equals"].items():
            got = _get_path(payload, p)
            assert got == v, f"expected {p}={v!r}, got {got!r}"

    if "json_path_contains" in expect:
        assert isinstance(payload, dict), f"json_path_contains expects dict, got {_type_name(payload)}"
        for p, sub in expect["json_path_contains"].items():
            got = _get_path(payload, p)
            assert isinstance(got, str), f"expected {p} to be str for contains check, got {_type_name(got)}"
            assert sub.lower() in got.lower(), f"expected {p} to contain {sub!r}, got {got!r}"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="tests/tests.json")
    args = ap.parse_args(argv)

    spec = json.loads(open(args.spec, "r", encoding="utf-8").read())
    tests = spec.get("tests", [])

    client = TestClient(app)
    ctx = RunContext()

    passed = 0
    failed = 0

    for t in tests:
        tid = t.get("id", "?")
        name = t.get("name", "")
        try:
            resp = _run_single(client, t["request"], ctx)
            _assert(resp, t.get("expect", {}), ctx)
            passed += 1
            print(f"[PASS] {tid} {name}")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {tid} {name}: {e}")

    print(f"\nSummary: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
