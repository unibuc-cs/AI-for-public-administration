import os
import httpx

def make_async_client(**kwargs) -> httpx.AsyncClient:
    # default timeout (seconds)
    timeout_s = float(os.getenv("HTTPX_TIMEOUT", "30"))
    timeout = httpx.Timeout(timeout_s)

    # You can also add limits if needed:
    # limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)

    return httpx.AsyncClient(timeout=timeout, **kwargs)
