"""Application factory.

Everything the shell needs is assembled here: the database, sessions, CSRF,
the first-run gate, security headers, error pages, the template globals the
layout reads, migrations and the background worker. Blueprints hold the routes.
"""
import logging
import os
import secrets
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException

from .config import Config
from .models import User, db, utcnow
from .core import models as _core_models  # noqa: F401  (the shared tables, for create_all)

#: The single source of truth for the version. tools/bump-version.sh edits this
#: line; the About section, /healthz, the release scripts and the Docker tags all
#: read it from here.
__version__ = "0.1.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hyprvolt")

_worker_lock = threading.Lock()
_worker_running = False


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL lets the web threads read while the worker writes; busy_timeout makes
    a writer wait for the lock instead of failing at once; SQLite leaves foreign
    keys off unless asked."""
    if type(dbapi_conn).__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    if app.config["TRUST_PROXY"] > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = app.config["TRUST_PROXY"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None   # the sign-in page explains itself

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        if _wants_json():
            return jsonify(error="You are signed out. Reload the page to sign in again."), 401
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    from . import auth, cli, main, registry, setup
    # Modules first: they are imported before create_all so their tables
    # exist, turned on or not, and the registry adds the /<module> URL
    # converter the main blueprint's routes use.
    modules = registry.discover(app.config["MODULE_PACKAGES"], strict=app.config["MODULES_STRICT"])
    registry.init_app(app, modules)
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(setup.bp)
    from .core import api as core_api
    app.register_blueprint(core_api.bp)
    app.register_blueprint(core_api.files_bp)
    from .core import views as core_views
    app.register_blueprint(core_views.bp)
    cli.register(app)


    @app.before_request
    def steer_to_setup():
        """A fresh install (zero users) goes to the wizard, nowhere else."""
        if request.endpoint in ("setup.wizard", "setup.submit", "static", "main.healthz"):
            return None
        if setup.needs_setup():
            return redirect(url_for("setup.wizard"))
        return None

    # ———— CSRF: a session token, no extension ————
    # Forms post it as a hidden _csrf field; the JSON API sends it as X-CSRF.

    def csrf_token() -> str:
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    @app.before_request
    def check_csrf():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        sent = request.headers.get("X-CSRF") or request.form.get("_csrf") or ""
        expected = session.get("_csrf", "")
        if not expected or not secrets.compare_digest(sent, expected):
            return jsonify(error="Your session expired. Reload the page and try again."), 400
        return None

    @app.after_request
    def headers(resp):
        # Dynamic pages must never be replayed from the browser cache: a stale
        # page briefly shows records the user has since changed or deleted.
        if resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return resp

    # ———— Errors: JSON for the API, a page for people ————

    @app.errorhandler(HTTPException)
    def http_error(err):
        if _wants_json():
            return jsonify(error=err.description or err.name), err.code
        return render_template("error.html", code=err.code, title=err.name,
                               message=_ERROR_TEXT.get(err.code, err.description)), err.code

    @app.errorhandler(Exception)
    def server_error(err):
        log.exception("unhandled error on %s %s", request.method, request.path)
        db.session.rollback()
        if _wants_json():
            return jsonify(error="Something went wrong on the server."), 500
        return render_template("error.html", code=500, title="Server error",
                               message=_ERROR_TEXT[500]), 500

    # ———— Template globals ————

    @app.template_global()
    def static_url(filename: str) -> str:
        """Static URL with an mtime cache-buster, so a redeploy invalidates
        browser caches at once."""
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    @app.template_global()
    def url_with(**changes) -> str:
        """This page's URL with some query parameters changed; None removes
        one. Paging and the open record never carry over."""
        from urllib.parse import urlencode
        args = {k: v for k, v in request.args.items() if k not in ("page", "partial", "open", "tab")}
        for key, value in changes.items():
            if value is None:
                args.pop(key, None)
            else:
                args[key] = value
        return request.path + ("?" + urlencode(args) if args else "")

    @app.context_processor
    def inject_globals():
        return {
            "csrf_token": csrf_token,
            "turnstile_site_key": (auth.turnstile_config() or {}).get("site_key", ""),
            "allow_registration": auth.registration_open(),
            "app_name": app.config["APP_NAME"],
            "app_tagline": app.config["APP_TAGLINE"],
            "source_url": app.config["SOURCE_URL"],
            "app_version": __version__,
            # The package name, which is also the container name in compose.
            "app_package": app.import_name,
        }

    from . import about_docs
    app.jinja_env.globals["app_changelog"] = about_docs.changelog

    @app.template_filter("ago")
    def ago(dt: datetime) -> str:
        seconds = int((utcnow() - dt).total_seconds())
        if seconds < 60:
            return "now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 7:
            return f"{days}d ago"
        if days < 365:
            return dt.strftime("%b %-d")
        return dt.strftime("%b %-d, %Y")

    from .permissions import check_routes
    check_routes(app)

    with app.app_context():
        db.create_all()
        _migrate(app)

    _start_worker(app)
    return app


_ERROR_TEXT = {
    400: "The request did not make sense to the server.",
    403: "Your account does not have access to this.",
    404: "There is nothing at this address.",
    405: "That action is not available here.",
    429: "Too many attempts. Wait a few minutes and try again.",
    500: "Something went wrong on the server. It has been logged.",
}


def _wants_json() -> bool:
    """API callers get JSON errors; page loads get the error page."""
    if request.headers.get("X-CSRF") or request.is_json:
        return True
    # HTML first: a client that accepts anything (curl, */*) gets the page;
    # only one that asks for JSON by name gets JSON.
    best = request.accept_mimetypes.best_match(["text/html", "application/json"])
    return best == "application/json"


def _migrate(app: Flask) -> None:
    """In-place migrations for databases created by older versions.

    The core's steps run first, then each module's, in the registry's fixed
    migration order (``registry.migration_order``). Every step checks before
    it acts, so it is safe to run on every boot and safe to run twice. Add new
    steps at the end of their list and never edit an old one: an install that
    has already run it will not run it again. When a step is needed at all is
    in migrate.py and docs/ARCHITECTURE.md. A step that makes the database
    unreadable to the previous version is a MAJOR release (docs/RELEASING.md).
    """
    from .migrate import Migrator
    from .registry import current

    core = Migrator("core")
    # The shape every step takes.
    core.add_column("users", "infinite_scroll", "BOOLEAN NOT NULL DEFAULT 1")
    core.add_column("users", "can_see_secrets", "BOOLEAN NOT NULL DEFAULT 0")
    # Admins of an install from before the vault keep what they could do:
    # they are the ones who would have been told the passwords anyway.
    core.once("secrets-for-admins", lambda: User.query.filter_by(role="admin").update({"can_see_secrets": True}))

    for module, step in current().migration_steps():
        step.run(Migrator(module.id))

    # After the modules' steps, so their tables are whole: the reminders of
    # an install from before they existed, without waiting for the worker.
    from .core.reminders import refresh_all
    core.once("reminders-first-fill", refresh_all)


def _start_worker(app: Flask) -> None:
    """Background thread for periodic work (worker.py).

    Gunicorn runs one worker with threads on purpose (see the Dockerfile): this
    thread must start exactly once, and SQLite prefers a single writing process.
    """
    global _worker_running
    if app.config["WORKER_MINUTES"] <= 0 or app.config.get("TESTING"):
        return
    # Avoid a double start under the werkzeug reloader's parent process.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    with _worker_lock:
        if _worker_running:
            return
        _worker_running = True

    from .models import int_setting
    from .worker import run_once

    def loop():
        time.sleep(20)  # let the app finish booting first
        while True:
            # An admin can change the cadence at runtime; re-read it each cycle.
            with app.app_context():
                minutes = int_setting("worker_minutes", app.config["WORKER_MINUTES"])
            if minutes > 0:
                try:
                    run_once(app)
                except Exception:
                    log.exception("background work failed")
            time.sleep(max(minutes, 1) * 60)

    threading.Thread(target=loop, daemon=True, name="hyprvolt-worker").start()
