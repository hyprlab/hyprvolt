"""Test fixtures.

Every test gets its own temporary data directory and database, so nothing
touches the developer's var/ and the tests run in any order.
"""
import importlib
import re

import pytest

CSRF_RE = re.compile(rb'name="csrf" content="([^"]+)"')


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WORKER_MINUTES", "0")
    monkeypatch.setenv("SECRET_KEY", "test-key")

    # config reads the environment at import time, so reload it after the
    # variables above are set.
    import hyprprem
    import hyprprem.auth
    import hyprprem.config
    import hyprprem.setup
    importlib.reload(hyprprem.config)
    # Process-wide caches that assume one database for the life of the process.
    hyprprem.setup._completed["done"] = False
    hyprprem.auth._failures.clear()

    class TestConfig(hyprprem.config.Config):
        TESTING = True

    yield hyprprem.create_app(TestConfig)


def token_for(client) -> str:
    """The session's CSRF token, read out of a page the way a browser would."""
    page = client.get("/login", follow_redirects=True)
    return CSRF_RE.search(page.data).group(1).decode()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def csrf(client):
    return token_for(client)


@pytest.fixture()
def admin(client, csrf):
    """A signed-in admin, created through the setup wizard."""
    resp = client.post("/setup", json={
        "username": "admin@example.com", "password": "password1",
        "name": "Ada", "registration_open": True, "worker_minutes": 0,
    }, headers={"X-CSRF": csrf})
    assert resp.status_code == 200
    return {"username": "admin@example.com", "password": "password1"}


@pytest.fixture()
def second_user(app, admin):
    """A second, non-admin account, signed in on its own client."""
    other = app.test_client()
    token = token_for(other)
    resp = other.post("/register", data={
        "_csrf": token, "username": "other@example.com",
        "password": "password1", "confirm": "password1",
    })
    assert resp.status_code == 302
    return other, token
