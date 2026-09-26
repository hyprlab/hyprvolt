"""API tokens: scripts use the JSON API with a Bearer token, as their user,
without a session or a CSRF token; tokens can be read-only and never read
secrets."""
from .conftest import make


def made(client, h, read_only=True, name="Script"):
    resp = client.post("/account/tokens", json={"name": name, "read_only": "1" if read_only else "0"}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    got = resp.get_json()
    assert got["token"] in got["html"] and got["token"].startswith("hv_")
    return got["token"], got["api_token"]["id"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_token_reads_and_writes_without_a_session(app, client, h, admin):
    server = make(client, h, "server", name="srv1")
    token, _ = made(client, h, read_only=False)
    script = app.test_client()                  # no cookies, no CSRF token
    listed = script.get("/api/entities?type=server", headers=bearer(token))
    assert [e["name"] for e in listed.get_json()["entities"]] == ["srv1"]
    created = script.post("/api/entities", json={"type": "server", "name": "srv2", "f.ram_gb": 64},
                          headers=bearer(token))
    assert created.status_code == 200
    changed = script.post(f"/api/entities/{server['id']}", json={"f.model": "R730xd"}, headers=bearer(token))
    assert changed.get_json()["entity"]["fields"]["model"] == "R730xd"
    history = client.get(f"/api/entities/{server['id']}/history").get_json()["history"]
    assert history[0]["user"] == "Ada"
    assert "Set-Cookie" not in listed.headers
    tokens = client.get("/account/tokens").get_json()["tokens"]
    assert tokens[0]["last_used_at"] is not None and tokens[0]["prefix"] == token[:9]


def test_a_read_only_token_cannot_change_anything(app, client, h, admin):
    token, _ = made(client, h, read_only=True)
    script = app.test_client()
    assert script.get("/api/entities", headers=bearer(token)).status_code == 200
    refused = script.post("/api/entities", json={"type": "server", "name": "x"}, headers=bearer(token))
    assert refused.status_code == 403 and "can only read" in refused.get_json()["error"]


def test_a_token_has_its_users_role(app, client, h, admin, viewer):
    other, oh = viewer
    token, _ = made(other, oh, read_only=False)
    script = app.test_client()
    assert script.get("/api/entities", headers=bearer(token)).status_code == 200
    assert script.post("/api/entities", json={"type": "server", "name": "x"}, headers=bearer(token)).status_code == 403


def test_bad_and_revoked_tokens_are_refused(app, client, h, admin):
    token, tid = made(client, h)
    script = app.test_client()
    for value in ("hv_nope", "not-even-close", ""):
        resp = script.get("/api/entities", headers=bearer(value))
        assert resp.status_code == 401 and "isn't valid" in resp.get_json()["error"]
    undo = client.post(f"/account/tokens/{tid}/revoke", headers=h).get_json()["undo"]
    assert script.get("/api/entities", headers=bearer(token)).status_code == 401
    client.post(undo["url"], json=undo["body"], headers=h)
    assert script.get("/api/entities", headers=bearer(token)).status_code == 200
    # Someone else's token is not yours to revoke.
    assert client.post("/account/tokens/999/revoke", headers=h).status_code == 404


def test_a_token_never_reads_a_secret_or_makes_tokens(app, client, h, admin):
    server = make(client, h, "server", name="srv1")
    sid = client.post(f"/vault/entities/{server['id']}/secrets", json={"name": "root", "value": "hunter2"},
                      headers=h).get_json()["secret"]["id"]
    token, _ = made(client, h, read_only=False)
    script = app.test_client()
    assert script.get(f"/vault/entities/{server['id']}/secrets", headers=bearer(token)).status_code == 200
    refused = script.post(f"/vault/secrets/{sid}/reveal", headers=bearer(token))
    assert refused.status_code == 403 and "API token" in refused.get_json()["error"]
    assert script.post("/account/tokens", json={"name": "more"}, headers=bearer(token)).status_code == 403


def test_tokens_are_listed_in_settings_and_go_with_their_user(app, client, h, admin, viewer):
    other, oh = viewer
    token, _ = made(other, oh, name="Backup script")
    page = other.get("/").data.decode()
    assert "Backup script" in page and token not in page and token[:9] + "…" in page
    assert "Name the token" in other.post("/account/tokens", json={"name": " "}, headers=oh).get_json()["error"]
    client.post("/admin/users/2/delete", headers=h)
    assert app.test_client().get("/api/entities", headers=bearer(token)).status_code == 401
