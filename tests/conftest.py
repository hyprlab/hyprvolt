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
    import hyprvolt
    import hyprvolt.auth
    import hyprvolt.config
    import hyprvolt.setup
    importlib.reload(hyprvolt.config)
    # Process-wide caches that assume one database for the life of the process.
    hyprvolt.setup._completed["done"] = False
    hyprvolt.auth._failures.clear()

    class TestConfig(hyprvolt.config.Config):
        TESTING = True
        # The example module (tests/example_modules) is loaded next to the
        # real ones, and a broken manifest fails the test instead of hiding.
        MODULE_PACKAGES = ["hyprvolt.modules", "tests.example_modules"]
        MODULES_STRICT = True

    yield hyprvolt.create_app(TestConfig)


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


@pytest.fixture()
def h(csrf):
    """Headers for the admin's JSON calls."""
    return {"X-CSRF": csrf}


@pytest.fixture()
def viewer(second_user):
    """The second account, left as a viewer: (client, headers)."""
    other, token = second_user
    return other, {"X-CSRF": token}


@pytest.fixture()
def editor(client, h, second_user):
    """The second account, made an editor: (client, headers)."""
    client.post("/admin/users/2/role", json={"role": "editor"}, headers=h)
    other, token = second_user
    return other, {"X-CSRF": token}


def make(client, h, type_="gadget", **data):
    """Create an entity through the API and return its JSON."""
    resp = client.post("/api/entities", json={"type": type_, **data}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["entity"]


def section(html: str, key: str) -> str:
    """One section of a record's sheet, which holds every section."""
    return html.split(f'data-panel="{key}"', 1)[1].split('data-panel="', 1)[0]
