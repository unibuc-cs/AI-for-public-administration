# debug_http.py
from __future__ import annotations

import time
import traceback
from fastapi import Request


async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    if request.url.path.startswith("/local/uploads"):
        ua = request.headers.get("user-agent", "-")
        ref = request.headers.get("referer", "-")
        origin = request.headers.get("origin", "-")
        print(f"[UPLOADS] {request.method} {request.url} UA={ua} REF={ref} ORIGIN={origin}")

    try:
        response = await call_next(request)
    except Exception:
        dt = (time.perf_counter() - t0) * 1000
        print(f"[HTTP] !! {request.method} {request.url.path}?{request.url.query} -> exception in {dt:.1f}ms")
        print("".join(traceback.format_exc()))
        raise

    dt = (time.perf_counter() - t0) * 1000
    return response

