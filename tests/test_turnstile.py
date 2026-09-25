"""Cloudflare Turnstile, configured in Settings > Security.

Cloudflare is never called: siteverify is replaced by a stand-in that accepts
one known token, so the tests cover the app's decisions, not the network.
"""
import pytest

from hyprvolt import auth

GOOD_TOKEN = "passes"


@pytest.fixture(autouse=True)
def fake_cloudflare(monkeypatch):
    """Accept GOOD_TOKEN with any secret except "wrong-secret"."""
    class Response:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def post(url, data, timeout):
        if data["secret"] == "wrong-secret":
            return Response({"success": False, "error-codes": ["invalid-input-secret"]})
        if data["response"] != GOOD_TOKEN:
            return Response({"success": False, "error-codes": ["invalid-input-response"]})
        return Response({"success": True})

    monkeypatch.setattr(auth.requests, "post", post)


def turn_on(client, csrf, **overrides):
    body = {"site_key": "site-123", "secret_key": "secret-abcd", "token": GOOD_TOKEN, **overrides}
    return client.post("/admin/turnstile", json=body, headers={"X-CSRF": csrf})


def test_off_by_default(client, csrf, admin):
    body = client.get("/").data.decode()
    assert 'id="ts-chip">Off' in body


def test_turning_on_needs_a_passed_challenge(client, csrf, admin):
    resp = turn_on(client, csrf, token="")
    assert resp.status_code == 400 and "challenge" in resp.get_json()["error"].lower()
    resp = turn_on(client, csrf, token="bad")
    assert resp.status_code == 400
    # Nothing was saved by the failures: sign-in still has no challenge.
    client.post("/logout", headers={"X-CSRF": csrf})
    assert b"cf-turnstile" not in client.get("/login").data


def test_a_wrong_secret_is_refused_in_words(client, csrf, admin):
    resp = turn_on(client, csrf, secret_key="wrong-secret")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Cloudflare doesn't recognize that secret key."


def test_turned_on_the_sign_in_page_needs_the_challenge(client, csrf, admin, app):
    resp = turn_on(client, csrf)
    assert resp.status_code == 200 and resp.get_json()["status"]["on"] is True

    stranger = app.test_client()
    page = stranger.get("/login")
    assert b'data-sitekey="site-123"' in page.data
    from tests.conftest import CSRF_RE
    token = CSRF_RE.search(page.data).group(1).decode()
    creds = {"_csrf": token, "username": admin["username"], "password": admin["password"]}
    assert stranger.post("/login", data=creds).status_code == 400
    creds["cf-turnstile-response"] = GOOD_TOKEN
    assert stranger.post("/login", data=creds).status_code == 302


def test_the_secret_never_reaches_the_page(client, csrf, admin):
    turn_on(client, csrf)
    body = client.get("/").data.decode()
    assert "secret-abcd" not in body
    assert "ends in abcd" in body


def test_blank_secret_keeps_the_saved_one(client, csrf, admin):
    turn_on(client, csrf)
    resp = turn_on(client, csrf, site_key="site-456", secret_key="")
    assert resp.status_code == 200
    assert resp.get_json()["status"]["site_key"] == "site-456"
    assert resp.get_json()["status"]["secret_hint"] == "abcd"


def test_turning_off_wins_over_the_environment(client, csrf, admin, app):
    app.config["TURNSTILE_SITE_KEY"] = "env-site"
    app.config["TURNSTILE_SECRET_KEY"] = "env-secret"
    status = client.get("/").data.decode()
    assert "From the TURNSTILE_SITE_KEY" in status
    resp = client.post("/admin/turnstile/disable", headers={"X-CSRF": csrf})
    assert resp.get_json()["status"]["on"] is False
    client.post("/logout", headers={"X-CSRF": csrf})
    assert b"cf-turnstile" not in client.get("/login").data


def test_only_admins_can_change_it(second_user):
    other, token = second_user
    assert other.post("/admin/turnstile", json={"site_key": "x", "token": GOOD_TOKEN},
                      headers={"X-CSRF": token}).status_code == 403
    assert other.post("/admin/turnstile/disable", headers={"X-CSRF": token}).status_code == 403


def test_security_section_is_admin_only(client, csrf, admin, second_user):
    assert 'data-pane="security"' in client.get("/").data.decode()
    other, _ = second_user
    assert 'data-pane="security"' not in other.get("/").data.decode()


def test_cli_turns_it_off(client, csrf, admin, app):
    turn_on(client, csrf)
    runner = app.test_cli_runner()
    assert "on" in runner.invoke(args=["turnstile", "status"]).output
    result = runner.invoke(args=["turnstile", "off"])
    assert result.exit_code == 0, result.output
    assert "off" in runner.invoke(args=["turnstile", "status"]).output
