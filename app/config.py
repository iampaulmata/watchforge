import os
from pathlib import Path

def read_secret(name: str) -> str | None:
    path = f"/run/secrets/{name}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

class Settings:
    DB_PATH = os.getenv("DASH_DB_PATH", "/data/dashboard.db")

    ADMIN_USER = os.getenv("DASH_ADMIN_USER", "admin")
    ADMIN_PASSWORD = read_secret("dash_admin_password") or os.getenv("DASH_ADMIN_PASSWORD", "")

    BESZEL_BASE_URL = os.getenv("BESZEL_BASE_URL", "").rstrip("/")
    BESZEL_EMAIL = read_secret("beszel_email") or ""
    BESZEL_PASSWORD = read_secret("beszel_password") or ""

    DOZZLE_BASE_URL = os.getenv("DOZZLE_BASE_URL", "").rstrip("/")

    POLL_HEALTH_SECONDS = getenv_int("DASH_POLL_HEALTH_SECONDS", 10)
    POLL_METRICS_SECONDS = getenv_int("DASH_POLL_METRICS_SECONDS", 10)

    WARN_PCT = getenv_int("DASH_WARN_PCT", 80)
    DANGER_PCT = getenv_int("DASH_DANGER_PCT", 95)

    ENCRYPTION_KEY = read_secret("app_encryption_key") or ""
