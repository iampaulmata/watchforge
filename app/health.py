import time
import requests
from typing import Any

def run_health_check(url: str, *, headers: dict[str, str] | None = None,
                     basic_user: str | None = None, basic_pass: str | None = None,
                     timeout=2.5) -> dict[str, Any]:
    t0 = time.time()
    try:
        auth = (basic_user, basic_pass) if basic_user and basic_pass else None
        r = requests.get(url, headers=headers or {}, auth=auth, timeout=timeout, allow_redirects=True)
        ms = int((time.time() - t0) * 1000)
        ok = 200 <= r.status_code < 400
        return {"ok": ok, "status_code": r.status_code, "latency_ms": ms, "error": None}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"ok": False, "status_code": None, "latency_ms": ms, "error": str(e)}
