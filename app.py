from flask import Flask, render_template, jsonify
import os
import time
import requests
from urllib.parse import urlparse

app = Flask(__name__)

import unicodedata
import re

def normalize_name(s: str) -> str:
    """
    Normalize names for matching:
    - remove emoji & symbols
    - normalize unicode
    - lowercase
    - trim whitespace
    """
    if not s:
        return ""

    # Normalize unicode (NFKD separates characters from modifiers)
    s = unicodedata.normalize("NFKD", s)

    # Remove all symbol characters (emoji live here)
    s = "".join(
        ch for ch in s
        if not unicodedata.category(ch).startswith("S")
    )

    # Collapse whitespace, lowercase
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


# -----------------------------
# Edit your services here
# -----------------------------
SERVICES = [
    {
        "id": "immich",
        "name": "Immich",
        "url": "http://arborlon:2283",
        "health_url": "http://arborlon",  # change to a specific health endpoint if you have one
        "method": "GET",
        "timeout": 2.0,
        "expected_status": [200, 301, 302],

        # Beszel mapping (you provided these)
        "beszel_host": "arborlon",
        "beszel_container": "immich_server",

        # Dozzle base (you provided this)
        "dozzle_base": "http://paranor:8080",
    },
]

# Beszel Hub (you provided this)
BESZEL_BASE_URL = os.environ.get("BESZEL_BASE_URL", "http://arborlong:8090").rstrip("/")

# Optional: if Beszel requires login, set these env vars and the dashboard will auth
BESZEL_EMAIL = os.environ.get("BESZEL_EMAIL")
BESZEL_PASSWORD = os.environ.get("BESZEL_PASSWORD")

# PocketBase auth token cache
_PB_TOKEN = None
_PB_TOKEN_AT = 0
_PB_TOKEN_TTL = 60 * 20  # 20 minutes (safe default)

def _hostname_from_url(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url

def check_service(service: dict) -> dict:
    url = service.get("health_url") or service["url"]
    method = service.get("method", "GET").upper()
    timeout = float(service.get("timeout", 2.0))
    expected = set(service.get("expected_status", [200]))

    started = time.perf_counter()
    try:
        resp = requests.request(method, url, timeout=timeout, allow_redirects=True)
        ms = int((time.perf_counter() - started) * 1000)
        ok = resp.status_code in expected
        return {
            "id": service["id"],
            "name": service["name"],
            "url": service["url"],
            "host": _hostname_from_url(service["url"]),
            "ok": ok,
            "status_code": resp.status_code,
            "latency_ms": ms,
            "checked_at": int(time.time()),
            "error": None if ok else f"Unexpected status {resp.status_code}",
        }
    except requests.exceptions.Timeout:
        ms = int((time.perf_counter() - started) * 1000)
        return {
            "id": service["id"],
            "name": service["name"],
            "url": service["url"],
            "host": _hostname_from_url(service["url"]),
            "ok": False,
            "status_code": None,
            "latency_ms": ms,
            "checked_at": int(time.time()),
            "error": "Timeout",
        }
    except requests.exceptions.RequestException as e:
        ms = int((time.perf_counter() - started) * 1000)
        return {
            "id": service["id"],
            "name": service["name"],
            "url": service["url"],
            "host": _hostname_from_url(service["url"]),
            "ok": False,
            "status_code": None,
            "latency_ms": ms,
            "checked_at": int(time.time()),
            "error": str(e),
        }

# -----------------------------
# Beszel (PocketBase) helpers
# -----------------------------
def _pb_get_token():
    global _PB_TOKEN, _PB_TOKEN_AT

    if not (BESZEL_EMAIL and BESZEL_PASSWORD):
        return None

    now = int(time.time())
    if _PB_TOKEN and (now - _PB_TOKEN_AT) < _PB_TOKEN_TTL:
        return _PB_TOKEN

    auth_url = f"{BESZEL_BASE_URL}/api/collections/_superusers/auth-with-password"
    resp = requests.post(
        auth_url,
        json={"identity": BESZEL_EMAIL, "password": BESZEL_PASSWORD},
        timeout=3.0,
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()

    token = data.get("token")
    if not token:
        raise RuntimeError("No token returned from _superusers auth")

    _PB_TOKEN = token
    _PB_TOKEN_AT = now
    return _PB_TOKEN


def _pb_headers() -> dict:
    headers = {"Accept": "application/json"}
    tok = _pb_get_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers

def pb_list(collection: str, *, per_page=200, page=1, filter_str=None, sort=None, fields=None, expand=None):
    url = f"{BESZEL_BASE_URL}/api/collections/{collection}/records"
    params = {"perPage": per_page, "page": page}
    if filter_str:
        params["filter"] = filter_str
    if sort:
        params["sort"] = sort
    if fields:
        params["fields"] = fields
    if expand:
        params["expand"] = expand

    resp = requests.get(url, params=params, headers=_pb_headers(), timeout=3.0)

    # 👇 Add this:
    if resp.status_code == 403:
        raise RuntimeError(f"Forbidden (403) for {collection}: check superuser auth / rules")

    resp.raise_for_status()
    return resp.json()

def build_metrics_index():
    """
    Pull:
      - systems (hosts)
      - containers (expand system)
      - latest container_stats per container (best-effort)
    """
    out = {
        "checked_at": int(time.time()),
        "systems_by_name": {},
        "containers_by_key": {},  # "host::container_name" -> container record
        "container_stats_by_id": {},  # container_id -> latest stats record
        "errors": [],
    }

    try:
        systems = pb_list("systems", per_page=200, fields="id,name,status,cpu,mem_used,mem_total,updated,created")  # fields are best-effort
        for rec in systems.get("items", []):
            name = rec.get("name")
            if name:
                out["systems_by_name"][name] = rec
    except Exception as e:
        out["errors"].append(f"systems: {e}")

    try:
        # expand system so we can map container -> host name
        containers = pb_list("containers", per_page=400, expand="system")
        for rec in containers.get("items", []):
            cname = rec.get("name")
            system_name = None
            exp = rec.get("expand") or {}
            sysrec = exp.get("system")
            if isinstance(sysrec, dict):
                system_name = sysrec.get("name")

            if system_name and cname:
                out["containers_by_key"][f"{system_name}::{cname}"] = rec
    except Exception as e:
        out["errors"].append(f"containers: {e}")

    # Latest stats per container: pull a page sorted by newest and keep first seen per container
    try:
        stats = pb_list("container_stats", per_page=400, sort="-created")
        for rec in stats.get("items", []):
            cid = rec.get("container")
            if cid and cid not in out["container_stats_by_id"]:
                out["container_stats_by_id"][cid] = rec
    except Exception as e:
        out["errors"].append(f"container_stats: {e}")

    return out

def extract_system_metrics(system_rec: dict):
    # Beszel fields may vary by version — these are best-effort fallbacks.
    cpu = system_rec.get("cpu") or system_rec.get("cpu_percent") or system_rec.get("cpuPercent")
    mem_used = system_rec.get("mem_used") or system_rec.get("mem_used_bytes") or system_rec.get("memoryUsed")
    mem_total = system_rec.get("mem_total") or system_rec.get("mem_total_bytes") or system_rec.get("memoryTotal")
    status = system_rec.get("status")
    return {"cpu": cpu, "mem_used": mem_used, "mem_total": mem_total, "status": status}

def extract_container_metrics(container_rec: dict, stats_rec: dict | None):
    # Container record may include status; stats record usually includes cpu/mem usage.
    status = container_rec.get("status") or container_rec.get("state")
    cpu = None
    mem_used = None

    if stats_rec:
        cpu = stats_rec.get("cpu") or stats_rec.get("cpu_percent") or stats_rec.get("cpuPercent")
        mem_used = stats_rec.get("mem_used") or stats_rec.get("mem_used_bytes") or stats_rec.get("memoryUsed")

    return {"status": status, "cpu": cpu, "mem_used": mem_used}

# -----------------------------
# Routes
# -----------------------------

@app.route("/api/beszel_systems")
def beszel_systems():
    payload = pb_list("systems", per_page=200, page=1)
    items = payload.get("items", [])

    # Show exactly what "name" is, plus helpful matching variants
    out = []
    for s in items:
        name = s.get("name")
        out.append({
            "id": s.get("id"),
            "name_raw": name,
            "name_lower": (name or "").lower(),
            "name_repr": repr(name),  # shows trailing spaces, weird chars, etc.
            "host": s.get("host"),
            "status": s.get("status"),
        })

    return jsonify({
        "count": len(out),
        "systems": out
    })

@app.route("/api/beszel_probe")
def beszel_probe():
    def safe_json(resp):
        try:
            return resp.json()
        except Exception:
            return {"_non_json": (resp.text or "")[:500]}

    result = {
        "base_url": BESZEL_BASE_URL,
        "has_email": bool(BESZEL_EMAIL),
        "has_password": bool(BESZEL_PASSWORD),
        "token_obtained": False,
        "collections": {},
        "raw_checks": {}
    }

    # 1) Can we obtain a token?
    try:
        tok = _pb_get_token()
        result["token_obtained"] = bool(tok)
    except Exception as e:
        result["raw_checks"]["auth_error"] = str(e)

    # 2) Can we list collections? (This reveals correct names: systems vs system, etc.)
    # PocketBase: GET /api/collections
    try:
        r = requests.get(f"{BESZEL_BASE_URL}/api/collections", headers=_pb_headers(), timeout=3.0)
        result["raw_checks"]["collections_status"] = r.status_code
        data = safe_json(r)
        # Return just the collection names for readability
        items = data.get("items", [])
        result["raw_checks"]["collection_names"] = [c.get("name") for c in items if c.get("name")]
    except Exception as e:
        result["raw_checks"]["collections_error"] = str(e)

    # 3) Try a few likely Beszel collections and report item counts (no guessing)
    for name in ["systems", "system_stats", "containers", "container_stats"]:
        try:
            kwargs = {"per_page": 5, "page": 1}
            if name in ("system_stats", "container_stats"):
                kwargs["sort"] = "-created"
            payload = pb_list(name, per_page=5, page=1, sort="-created")
            items = payload.get("items", [])
            first = items[0] if items else {}

            stats_obj = first.get("stats") if isinstance(first, dict) else None
            stats_keys = list(stats_obj.keys())[:50] if isinstance(stats_obj, dict) else []

            # Make a small, safe preview of stats (truncate big strings/arrays)
            stats_preview = {}
            if isinstance(stats_obj, dict):
                for k in list(stats_obj.keys())[:20]:
                    v = stats_obj.get(k)
                    if isinstance(v, (list, dict)):
                        stats_preview[k] = f"<{type(v).__name__}>"
                    elif isinstance(v, str) and len(v) > 80:
                        stats_preview[k] = v[:80] + "…"
                    else:
                        stats_preview[k] = v

            result["collections"][name] = {
                "items_count": len(items),
                "top_level_keys": list(first.keys())[:30],
                "stats_keys": stats_keys,
                "stats_preview": stats_preview,
            }
        except Exception as e:
            result["collections"][name] = {"error": str(e)}


    return jsonify(result)

@app.route("/api/beszel_auth_test")
def beszel_auth_test():
    try:
        # If auth works, this should return non-empty items (assuming you have systems)
        payload = pb_list("systems", per_page=5)
        return jsonify({
            "ok": True,
            "items_count": len(payload.get("items", [])),
            "sample": (payload.get("items") or [None])[0],
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    
@app.route("/")
def dashboard():
    return render_template("dashboard.html", services=SERVICES)

@app.route("/api/health")
def api_health():
    results = [check_service(svc) for svc in SERVICES]
    summary = {
        "total": len(results),
        "up": sum(1 for r in results if r["ok"]),
        "down": sum(1 for r in results if not r["ok"]),
        "checked_at": int(time.time()),
    }
    return jsonify({"summary": summary, "results": results})

@app.route("/api/metrics")
def api_metrics():
    out = {
        "checked_at": int(time.time()),
        "errors": [],
        "results": [],
    }

    def pb_first(collection, *, filter_str=None, sort=None):
        payload = pb_list(collection, per_page=1, page=1, filter_str=filter_str, sort=sort)
        items = payload.get("items", [])
        return items[0] if items else None

    def pick(d, *keys):
        for k in keys:
            if isinstance(d, dict) and d.get(k) is not None:
                return d.get(k)
        return None

    def gb_to_bytes(v):
        try:
            return float(v) * 1024 * 1024 * 1024
        except Exception:
            return None

    # ---- Load systems, build case-insensitive lookup ----
    try:
        systems_payload = pb_list("systems", per_page=200, page=1)
        systems = systems_payload.get("items", [])
        systems_by_normalized = {}
        for s in systems:
            raw_name = s.get("name")
            norm_name = normalize_name(raw_name)
            if norm_name:
                systems_by_normalized[norm_name] = s


    except Exception as e:
        out["errors"].append(f"systems list: {e}")
        systems_by_normalized = {}

    available = sorted(list(systems_by_normalized.keys()))
    out["_debug_system_names_lower"] = available

    for svc in SERVICES:
        host_name = svc.get("beszel_host") or ""
        ctr_name = svc.get("beszel_container") or ""

        # Case-insensitive system match
        system_rec = systems_by_normalized.get(host_name.lower())
        system_id = system_rec.get("id") if system_rec else None

        # ---- System metrics from latest system_stats ----
        system_metrics = {}
        if system_id:
            try:
                sstat = pb_first("system_stats", filter_str=f'system="{system_id}"', sort="-created")
                sstats = (sstat or {}).get("stats") or {}

                # From your probe, these exist:
                # cpu = percent, m = total GB, mu = used GB
                cpu_pct = pick(sstats, "cpu")
                mem_total_gb = pick(sstats, "m")
                mem_used_gb = pick(sstats, "mu")

                system_metrics = {
                    "cpu": cpu_pct,
                    "mem_used": gb_to_bytes(mem_used_gb) if mem_used_gb is not None else None,
                    "mem_total": gb_to_bytes(mem_total_gb) if mem_total_gb is not None else None,
                    "status": pick(system_rec, "status"),
                    "mem_percent": pick(sstats, "mp"),  # optional
                }
            except Exception as e:
                out["errors"].append(f"system_stats {host_name}: {e}")

        # ---- Container metrics from containers collection ----
        container_metrics = {"state": None, "uptime": None, "cpu": None, "mem_used": None, "mem_pct": None, "health": None}
        if system_id and ctr_name:
            try:
                crec = pb_first("containers", filter_str=f'system="{system_id}" && name="{ctr_name}"')
                if crec:
                    # Beszel containers.status is "Up X days" (uptime)
                    container_metrics["uptime"] = crec.get("status")

                    # Use health/status-ish info for the "state" line (best effort)
                    # health is numeric in your sample; 0 often means OK but we’ll map conservatively.
                    health = crec.get("health")
                    container_metrics["health"] = health
                    if health is None:
                        container_metrics["state"] = "Unknown"
                    elif isinstance(health, (int, float)) and health == 0:
                        container_metrics["state"] = "Unhealthy"
                    else:
                        container_metrics["state"] = "Healthy"

                    container_metrics["cpu"] = crec.get("cpu")

                    # memory from Beszel containers looks like a percentage in your example (96.88)
                    mem = crec.get("memory")

                    # In your Beszel "containers" collection, memory appears to be MB (e.g., 96.88)
                    # Convert MB -> bytes for UI formatBytes()
                    mem_bytes = None
                    try:
                        if isinstance(mem, (int, float)):
                            mem_bytes = float(mem) * 1024 * 1024
                    except Exception:
                        mem_bytes = None

                    container_metrics["mem_used"] = mem_bytes
                    container_metrics["mem_pct"] = None

                    # keep mem_used for compatibility (we’ll show % in UI)
                    container_metrics["mem_used"] = None
            except Exception as e:
                out["errors"].append(f"containers {host_name}::{ctr_name}: {e}")


        # Helpful “did we match?” flags (won’t break your JS)
        out["results"].append({
            "id": svc["id"],
            "beszel_host": host_name,
            "beszel_container": ctr_name,
            "system": system_metrics,
            "container": container_metrics,
            "_matched": {
                "system_found": bool(system_id),
                "container_found": (
                    container_metrics.get("state") is not None
                    or container_metrics.get("uptime") is not None
                    or container_metrics.get("cpu") is not None
                    or container_metrics.get("mem_used") is not None
                    or container_metrics.get("mem_pct") is not None
                )
            }
        })

    return jsonify(out)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
