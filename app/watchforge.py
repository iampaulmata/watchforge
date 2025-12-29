import json
import time
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, Response
from werkzeug.security import check_password_hash, generate_password_hash
from .db import db, Service, ServiceSecret, CheckResult, MetricsSnapshot, Theme, AppSetting

from apscheduler.schedulers.background import BackgroundScheduler

from .config import Settings
from .db import db, Service, ServiceSecret, CheckResult, MetricsSnapshot, Theme
from .crypto import Crypto
from .beszel import BeszelClient, normalize_name
from .health import run_health_check
from pathlib import Path
import re

from werkzeug.security import generate_password_hash

app = Flask(__name__)

def bootstrap():
    # session secret
    app.secret_key = (Settings.ENCRYPTION_KEY + "|session").encode("utf-8")[:32]

    # SQLAlchemy config + bind
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{Settings.DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if "sqlalchemy" not in app.extensions:
        db.init_app(app)

    # init things that rely on Settings only (no DB queries here)
    global crypto, beszel, _ADMIN_HASH
    crypto = Crypto(Settings.ENCRYPTION_KEY)
    beszel = BeszelClient(Settings.BESZEL_BASE_URL, Settings.BESZEL_EMAIL, Settings.BESZEL_PASSWORD)
    _ADMIN_HASH = generate_password_hash(Settings.ADMIN_PASSWORD) if Settings.ADMIN_PASSWORD else None

    # DB work must be inside app context
    with app.app_context():
        db.create_all()
        seed_starter_themes()

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:64]  # Theme.slug max 64

def seed_starter_themes():
    themes_dir = Path(__file__).resolve().parent / "themes"
    if not themes_dir.exists():
        return

    for p in sorted(themes_dir.glob("*.json")):
        with p.open("r", encoding="utf-8") as f:
            theme_doc = json.load(f)

        name = theme_doc.get("name") or p.stem
        slug = theme_doc.get("id") or _slugify(name) or _slugify(p.stem)
        if not slug:
            continue

        # Store only tokens in DB (matches your Theme model design)
        tokens = theme_doc.get("tokens") or {}
        tokens_json = json.dumps(tokens, separators=(",", ":"), ensure_ascii=False)

        existing = Theme.query.filter_by(slug=slug).first()
        if existing:
            # Optional: update starter themes on changes (recommended for dev)
            existing.name = name
            existing.author = theme_doc.get("author")
            existing.description = theme_doc.get("description")
            existing.mode = theme_doc.get("mode", existing.mode or "dark")
            existing.tokens_json = tokens_json
            # Keep starter themes private by default; user can publish explicitly
            existing.is_public = bool(existing.is_public)
        else:
            db.session.add(Theme(
                slug=slug,
                name=name,
                author=theme_doc.get("author"),
                description=theme_doc.get("description"),
                mode=theme_doc.get("mode", "dark"),
                tokens_json=tokens_json,
                is_public=False,
                created_by_user_id=None,
            ))

    db.session.commit()

        # seed admin (if you have User model)
    from .db import User  # adjust if User lives elsewhere
    if User.query.count() == 0:
        admin = User(
            username=Settings.ADMIN_USER,
            password_hash=generate_password_hash(Settings.ADMIN_PASSWORD),
        )
        db.session.add(admin)
        db.session.commit()


# Run bootstrap at import time, but ONLY after app is defined
bootstrap()

def get_active_theme_slug() -> str | None:
    row = AppSetting.query.get("active_theme_slug")
    return row.value if row else None

def set_active_theme_slug(slug: str):
    row = AppSetting.query.get("active_theme_slug")
    if row:
        row.value = slug
    else:
        db.session.add(AppSetting(key="active_theme_slug", value=slug))
    db.session.commit()

THEME_TOKENS_ALLOWED = {
    "--bg","--surface","--surface-2","--text","--muted","--border",
    "--accent","--accent-2","--good","--warn","--bad",
    "--ui-font","--mono-font","--text-size","--title-size",
    "--radius","--shadow","--blur","--glass",
    "--pad","--gap","--compact",
    "--warn-pct","--danger-pct"
}

def require_login():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return None

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", admin_user=Settings.ADMIN_USER)

    user = request.form.get("username", "")
    pw = request.form.get("password", "")

    if user == Settings.ADMIN_USER and _ADMIN_HASH and check_password_hash(_ADMIN_HASH, pw):
        session["logged_in"] = True
        session["user_id"] = 1
        return redirect(url_for("dashboard"))

    return render_template("login.html", admin_user=Settings.ADMIN_USER, error="Invalid credentials")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------- DB init + seed --------
with app.app_context():
    db.create_all()

# -------- UI routes --------
@app.route("/")
def dashboard():
    gate = require_login()
    if gate:
        return gate
    services = Service.query.filter_by(enabled=True).order_by(Service.group.asc().nullslast(), Service.name.asc()).all()
    return render_template("dashboard.html", services=services, warn_pct=Settings.WARN_PCT, danger_pct=Settings.DANGER_PCT)

@app.route("/services")
def services_page():
    gate = require_login()
    if gate:
        return gate
    services = Service.query.order_by(Service.group.asc().nullslast(), Service.name.asc()).all()
    return render_template("services.html", services=services)

@app.route("/services/new", methods=["GET", "POST"])
def service_new():
    gate = require_login()
    if gate:
        return gate

    if request.method == "GET":
        return render_template("service_form.html", svc=None)

    return _service_upsert()

@app.route("/services/<int:service_id>/edit", methods=["GET", "POST"])
def service_edit(service_id: int):
    gate = require_login()
    if gate:
        return gate

    svc = Service.query.get_or_404(service_id)
    if request.method == "GET":
        sec = ServiceSecret.query.get(service_id)
        headers = {}
        user = ""
        pw = ""
        if sec:
            user = crypto.decrypt(sec.enc_basic_user)
            pw = crypto.decrypt(sec.enc_basic_pass)
            try:
                headers = json.loads(crypto.decrypt(sec.enc_headers_json) or "{}")
            except Exception:
                headers = {}
        return render_template("service_form.html", svc=svc, secret_user=user, secret_pass=pw, secret_headers=headers)

    return _service_upsert(service_id=service_id)

@app.route("/services/<int:service_id>/delete", methods=["POST"])
def service_delete(service_id: int):
    gate = require_login()
    if gate:
        return gate
    ServiceSecret.query.filter_by(service_id=service_id).delete()
    Service.query.filter_by(id=service_id).delete()
    db.session.commit()
    return redirect(url_for("services_page"))

import re
import json
from flask import jsonify, request, abort

def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "theme"

def sanitize_tokens(tokens: dict) -> dict:
    out = {}
    for k, v in (tokens or {}).items():
        if k in THEME_TOKENS_ALLOWED:
            out[k] = str(v).replace("\n"," ").replace("\r"," ").strip()
    return out

@app.route("/themes")
def themes_list():
    gate = require_login()
    if gate: return gate

    active_slug = get_active_theme_slug()
    themes = Theme.query.order_by(Theme.name.asc()).all()
    return render_template("themes.html", themes=themes, active_slug=active_slug)

@app.route("/themes/<int:theme_id>/edit")
def themes_edit(theme_id):
    gate = require_login()
    if gate: return gate

    theme = Theme.query.get_or_404(theme_id)
    # You can enforce per-user ownership here if you want.
    tokens = {}
    try:
        tokens = json.loads(theme.tokens_json)
    except Exception:
        tokens = {}
    return render_template("themes_editor.html", theme=theme, tokens_json=tokens)

@app.route("/themes/create", methods=["POST"])
def themes_create():
    gate = require_login()
    if gate: return jsonify({"error":"unauthorized"}), 401

    payload = request.get_json(force=True)
    meta = payload.get("meta") or {}
    tokens = sanitize_tokens(payload.get("tokens") or {})

    name = (meta.get("name") or "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400

    slug = slugify(name)
    # ensure uniqueness
    base = slug
    i = 2
    while Theme.query.filter_by(slug=slug).first():
        slug = f"{base}-{i}"
        i += 1

    theme = Theme(
        slug=slug,
        name=name,
        author=(meta.get("author") or "").strip() or None,
        description=(meta.get("description") or "").strip() or None,
        mode=meta.get("mode") if meta.get("mode") in ("light","dark") else "dark",
        is_public=bool(meta.get("is_public", False)),
        tokens_json=json.dumps(tokens),
        created_by_user_id=session["user_id"]
    )
    db.session.add(theme)
    db.session.commit()
    return jsonify({"ok": True, "id": theme.id})

@app.route("/themes/new")
def themes_new():
    gate = require_login()
    if gate: return gate
    return render_template("themes_editor.html", theme=None, tokens_json={})


@app.route("/themes/<int:theme_id>/update", methods=["POST"])
def themes_update(theme_id):
    gate = require_login()
    if gate: return jsonify({"error":"unauthorized"}), 401

    theme = Theme.query.get_or_404(theme_id)
    # Optional: enforce ownership (recommended)
    if theme.created_by_user_id != session["user_id"]:
        abort(403)

    payload = request.get_json(force=True)
    meta = payload.get("meta") or {}
    tokens = sanitize_tokens(payload.get("tokens") or {})

    name = (meta.get("name") or "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400

    theme.name = name
    theme.author = (meta.get("author") or "").strip() or None
    theme.description = (meta.get("description") or "").strip() or None
    theme.mode = meta.get("mode") if meta.get("mode") in ("light","dark") else theme.mode
    theme.is_public = bool(meta.get("is_public", False))
    theme.tokens_json = json.dumps(tokens)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/themes/import", methods=["POST"])
def themes_import():
    gate = require_login()
    if gate: return jsonify({"error":"unauthorized"}), 401

    data = request.get_json(force=True)
    if data.get("schema") != "homelab-dashboard-theme@1":
        return jsonify({"error":"bad schema"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error":"name required"}), 400

    slug = slugify(name)
    base = slug
    i = 2
    while Theme.query.filter_by(slug=slug).first():
        slug = f"{base}-{i}"
        i += 1

    tokens = sanitize_tokens(data.get("tokens") or {})
    mode = data.get("mode") if data.get("mode") in ("light","dark") else "dark"

    theme = Theme(
        slug=slug,
        name=name,
        author=(data.get("author") or "").strip() or None,
        description=(data.get("description") or "").strip() or None,
        mode=mode,
        is_public=False,  # private by default
        tokens_json=json.dumps(tokens),
        created_by_user_id=session["user_id"]
    )
    db.session.add(theme)
    db.session.commit()
    return jsonify({"ok": True, "id": theme.id})

@app.route("/theme.css")
def theme_css():
    # allow unauth; it’s just CSS
    slug = get_active_theme_slug()
    theme = Theme.query.filter_by(slug=slug).first() if slug else None

    tokens = {}
    if theme:
        try:
            tokens = json.loads(theme.tokens_json or "{}")
        except Exception:
            tokens = {}

    lines = []
    for k, v in tokens.items():
        if k in THEME_TOKENS_ALLOWED:
            safe_val = str(v).replace("\n"," ").replace("\r"," ").strip()
            lines.append(f"  {k}: {safe_val};")

    css = ":root{\n" + "\n".join(lines) + "\n}\n"
    if theme and theme.mode in ("light","dark"):
        css += f":root{{ color-scheme: {theme.mode}; }}\n"

    resp = Response(css, mimetype="text/css")

    # ✅ Per-user / session-dependent CSS should not be shared by caches
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Vary"] = "Cookie"

    return resp

@app.route("/themes/<int:theme_id>/activate", methods=["POST"])
def activate_theme(theme_id):
    gate = require_login()
    if gate: return gate

    theme = Theme.query.get_or_404(theme_id)
    set_active_theme_slug(theme.slug)
    return redirect(url_for("themes_list"))


@app.route("/themes/<int:theme_id>/export.json")
def export_theme(theme_id):
    t = Theme.query.get_or_404(theme_id)
    return jsonify({
        "schema": "homelab-dashboard-theme@1",
        "name": t.name,
        "author": t.author,
        "description": t.description,
        "mode": t.mode,
        "tokens": json.loads(t.tokens_json)
    })

@app.route("/themes/<int:theme_id>/publish", methods=["POST"])
def publish_theme(theme_id):
    theme = Theme.query.get_or_404(theme_id)
    if theme.created_by_user_id != session["user_id"]:
        abort(403)
    theme.is_public = not theme.is_public
    db.session.commit()
    return redirect(url_for("themes_page"))

def _service_upsert(service_id: int | None = None):
    form = request.form
    slug = (form.get("slug") or "").strip()
    name = (form.get("name") or "").strip()
    url = (form.get("url") or "").strip()
    health_url = (form.get("health_url") or "").strip()
    group = (form.get("group") or "").strip() or None
    beszel_host = (form.get("beszel_host") or "").strip() or None
    beszel_container = (form.get("beszel_container") or "").strip() or None
    dozzle_container = (form.get("dozzle_container") or "").strip() or None
    enabled = True if form.get("enabled") == "on" else False

    basic_user = (form.get("basic_user") or "").strip()
    basic_pass = (form.get("basic_pass") or "").strip()
    headers_raw = (form.get("headers_json") or "").strip()

    if not (slug and name and url and health_url):
        return Response("Missing required fields (slug, name, url, health_url)", status=400)

    try:
        headers_obj = json.loads(headers_raw) if headers_raw else {}
        if not isinstance(headers_obj, dict):
            raise ValueError("headers_json must be an object")
    except Exception as e:
        return Response(f"Invalid headers JSON: {e}", status=400)

    if service_id:
        svc = Service.query.get_or_404(service_id)
    else:
        svc = Service()

    svc.slug = slug
    svc.name = name
    svc.url = url
    svc.health_url = health_url
    svc.group = group
    svc.beszel_host = beszel_host
    svc.beszel_container = beszel_container
    svc.dozzle_container = dozzle_container
    svc.enabled = enabled

    db.session.add(svc)
    db.session.commit()

    sec = ServiceSecret.query.get(svc.id) or ServiceSecret(service_id=svc.id)
    sec.enc_basic_user = crypto.encrypt(basic_user) if basic_user else ""
    sec.enc_basic_pass = crypto.encrypt(basic_pass) if basic_pass else ""
    sec.enc_headers_json = crypto.encrypt(json.dumps(headers_obj)) if headers_obj else ""
    db.session.add(sec)
    db.session.commit()

    return redirect(url_for("services_page"))

# -------- Import/Export --------
@app.route("/services/export.json")
def services_export():
    gate = require_login()
    if gate:
        return gate
    services = Service.query.order_by(Service.group.asc().nullslast(), Service.name.asc()).all()
    payload = []
    for s in services:
        payload.append({
            "slug": s.slug,
            "name": s.name,
            "url": s.url,
            "health_url": s.health_url,
            "group": s.group,
            "beszel_host": s.beszel_host,
            "beszel_container": s.beszel_container,
            "dozzle_container": s.dozzle_container,
            "enabled": s.enabled
        })
    return jsonify(payload)

@app.route("/services/import.json", methods=["POST"])
def services_import():
    gate = require_login()
    if gate:
        return gate
    data = request.get_json(force=True, silent=False)
    if not isinstance(data, list):
        return Response("Expected a JSON array of services", status=400)

    for item in data:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        svc = Service.query.filter_by(slug=item["slug"]).first() or Service(slug=item["slug"])
        svc.name = item.get("name") or svc.slug
        svc.url = item.get("url") or ""
        svc.health_url = item.get("health_url") or svc.url
        svc.group = item.get("group")
        svc.beszel_host = item.get("beszel_host")
        svc.beszel_container = item.get("beszel_container")
        svc.dozzle_container = item.get("dozzle_container")
        svc.enabled = bool(item.get("enabled", True))
        db.session.add(svc)
    db.session.commit()
    return jsonify({"ok": True})

# -------- APIs consumed by dashboard.js --------
@app.route("/api/health")
def api_health():
    gate = require_login()
    if gate:
        return Response("unauthorized", status=401)

    services = Service.query.filter_by(enabled=True).all()
    now = int(time.time())

    results = []
    up = 0
    for s in services:
        sec = ServiceSecret.query.get(s.id)
        headers = {}
        user = ""
        pw = ""
        if sec:
            user = crypto.decrypt(sec.enc_basic_user)
            pw = crypto.decrypt(sec.enc_basic_pass)
            try:
                headers = json.loads(crypto.decrypt(sec.enc_headers_json) or "{}")
            except Exception:
                headers = {}

        r = run_health_check(s.health_url, headers=headers, basic_user=user, basic_pass=pw)
        results.append({
            "id": s.slug,
            "ok": r["ok"],
            "status_code": r["status_code"],
            "latency_ms": r["latency_ms"],
            "error": r["error"],
            "checked_at": now,
        })
        if r["ok"]:
            up += 1

        # persist (optional but you asked for persistence)
        db.session.add(CheckResult(
            service_id=s.id,
            checked_at=now,
            ok=r["ok"],
            status_code=r["status_code"],
            latency_ms=r["latency_ms"],
            error=r["error"],
        ))

    db.session.commit()

    return jsonify({
        "summary": {"total": len(services), "up": up, "down": len(services) - up, "checked_at": now},
        "results": results
    })

@app.route("/api/metrics")
def api_metrics():
    gate = require_login()
    if gate:
        return Response("unauthorized", status=401)

    services = Service.query.filter_by(enabled=True).all()
    now = int(time.time())

    # Build systems lookup by normalized name
    systems = beszel.list_records("systems", per_page=200, page=1).get("items", [])
    systems_by_norm = {normalize_name(s.get("name", "")): s for s in systems if s.get("name")}

    out = {"checked_at": now, "errors": [], "results": []}

    for s in services:
        sys_rec = systems_by_norm.get(normalize_name(s.beszel_host or ""))
        system_id = sys_rec.get("id") if sys_rec else None

        system_metrics = {}
        if system_id:
            try:
                ss = beszel.first_record("system_stats", filter_str=f'system="{system_id}"', sort="-created")
                stats = (ss or {}).get("stats") or {}
                # Your schema: cpu%, mu(used GB), m(total GB), mp(percent)
                cpu = stats.get("cpu")
                mu_gb = stats.get("mu")
                m_gb = stats.get("m")
                mp = stats.get("mp")
                system_metrics = {
                    "cpu": cpu,
                    "mem_used": (float(mu_gb) * 1024 * 1024 * 1024) if mu_gb is not None else None,
                    "mem_total": (float(m_gb) * 1024 * 1024 * 1024) if m_gb is not None else None,
                    "mem_percent": mp,
                }
            except Exception as e:
                out["errors"].append(f"system_stats {s.slug}: {e}")

        container_metrics = {"state": None, "uptime": None, "cpu": None, "mem_used": None}
        if system_id and s.beszel_container:
            try:
                c = beszel.first_record("containers", filter_str=f'system="{system_id}" && name="{s.beszel_container}"')
                if c:
                    # status is uptime string (e.g., "Up 7 days")
                    container_metrics["uptime"] = c.get("status")
                    # health: 0 in your sample corresponds to "Healthy" in Beszel UI; adjust if needed
                    health = c.get("health")
                    container_metrics["state"] = "Healthy" if health == 0 else "Unhealthy"
                    container_metrics["cpu"] = c.get("cpu")

                    # memory appears MB in your instance (e.g., 96.88, 255.4)
                    mem_mb = c.get("memory")
                    if isinstance(mem_mb, (int, float)):
                        container_metrics["mem_used"] = float(mem_mb) * 1024 * 1024
            except Exception as e:
                out["errors"].append(f"containers {s.slug}: {e}")

        out["results"].append({
            "id": s.slug,
            "beszel_host": s.beszel_host,
            "beszel_container": s.beszel_container,
            "system": system_metrics,
            "container": container_metrics
        })

        # persist snapshot
        db.session.add(MetricsSnapshot(
            service_id=s.id,
            checked_at=now,
            host_cpu=system_metrics.get("cpu"),
            host_mem_used_bytes=system_metrics.get("mem_used"),
            host_mem_total_bytes=system_metrics.get("mem_total"),
            host_mem_pct=system_metrics.get("mem_percent"),
            ctr_cpu=container_metrics.get("cpu"),
            ctr_mem_mb=(c.get("memory") if 'c' in locals() and c else None),
            ctr_uptime=container_metrics.get("uptime"),
            ctr_health=(c.get("health") if 'c' in locals() and c else None),
        ))

    db.session.commit()
    return jsonify(out)

# -------- Background polling (optional; APIs also persist on-demand) --------
sched = BackgroundScheduler(daemon=True)

def _poll_health_job():
    with app.app_context():
        # hit internal logic once; this persists results
        try:
            app.test_client().get("/api/health")
        except Exception:
            pass

def _poll_metrics_job():
    with app.app_context():
        try:
            app.test_client().get("/api/metrics")
        except Exception:
            pass

sched.add_job(_poll_health_job, "interval", seconds=Settings.POLL_HEALTH_SECONDS, id="poll_health", replace_existing=True)
sched.add_job(_poll_metrics_job, "interval", seconds=Settings.POLL_METRICS_SECONDS, id="poll_metrics", replace_existing=True)
sched.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
