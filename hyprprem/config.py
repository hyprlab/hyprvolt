"""Configuration.

Everything an operator can change is an environment variable with a working
default, so the app starts with no configuration at all. Values an admin
changes while the app runs live in the ``settings`` table instead (see
``models.get_setting``); the variables here are only the fresh-install
defaults for those.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Runtime state (the SQLite file, the generated secret key) lives here. In
# Docker it is the /data volume; locally it is ./var, which git ignores. The
# repository's own data/ directory holds tracked assets and is a different thing.
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "var"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key() -> str:
    """SECRET_KEY from the environment, otherwise a generated one kept in the
    data directory, so sessions survive a restart."""
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    keyfile = DATA_DIR / ".secret_key"
    if keyfile.exists():
        return keyfile.read_text().strip()
    key = secrets.token_hex(32)
    keyfile.write_text(key)
    keyfile.chmod(0o600)
    return key


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    APP_NAME = os.environ.get("APP_NAME", "Hyprprem")
    APP_TAGLINE = os.environ.get("APP_TAGLINE", "IT documentation for on-premise infrastructure.")
    # Where the About section's Source link points. Empty hides the link.
    SOURCE_URL = os.environ.get("SOURCE_URL", "https://github.com/hyprlab/hyprprem")

    SECRET_KEY = _secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'hyprprem.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # The session cookie. SESSION_COOKIE_SECURE stays off by default because
    # the app is often reached over plain HTTP on a LAN; turn it on behind TLS.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE", "0")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    # How many reverse proxies sit in front of the app (Cloudflare Tunnel,
    # Caddy, Traefik...). 0 trusts no X-Forwarded-* header at all. Setting it
    # higher than the real number lets a client spoof its own IP address.
    TRUST_PROXY = _int("TRUST_PROXY", 0)

    # Cloudflare Turnstile. Leave both unset to run without the challenge.
    TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
    TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

    # ——— Fresh-install defaults; an admin overrides these at runtime ———
    # Off by default: infrastructure documentation is rarely something strangers
    # should be able to sign up to read. New accounts start as viewers.
    ALLOW_REGISTRATION = _flag("ALLOW_REGISTRATION", "0")
    # Background worker cadence, in minutes. 0 keeps the thread from starting.
    WORKER_MINUTES = _int("WORKER_MINUTES", 15)
    ITEMS_PER_PAGE = _int("ITEMS_PER_PAGE", 40)
