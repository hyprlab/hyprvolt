"""Regressions for the security review: API tokens and the keys to
everything, crafted backups, writes that must find a live record, links in
secrets, and a new password ending other sessions."""
import io
import tarfile
from datetime import timedelta

from hyprvolt.models import ApiToken, db, utcnow

from .conftest import make, token_for


def token(client, h, read_only=True):
    got = client.post("/account/tokens", json={"name": "t", "read_only": "1" if read_only else "0"}, headers=h)
    return got.get_json()["token"], got.get_json()["api_token"]["id"]


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_no_token_gets_the_secrets_key_or_a_backup(app, client, h, admin):
    server = make(client, h, "server", name="srv1")
    client.post(f"/vault/entities/{server['id']}/secrets", json={"name": "root", "value": "hunter2"}, headers=h)
    name = client.post("/admin/backups", headers=h).get_json()["backup"]["name"]
    script = app.test_client()
    for read_only in (True, False):
        t, _ = token(client, h, read_only)
        assert script.get("/vault/key", headers=bearer(t)).status_code == 403
        assert script.get(f"/admin/backups/{name}", headers=bearer(t)).status_code == 403
        assert script.get("/admin/backups", headers=bearer(t)).status_code == 403
    t, _ = token(client, h, read_only=False)
    for url in ("/admin/backups", f"/admin/backups/{name}/restore", f"/admin/backups/{name}/delete", "/vault/key"):
        resp = script.post(url, headers=bearer(t))
        assert resp.status_code == 403 and "API token" in resp.get_json()["error"], url


def test_a_restore_revokes_every_token(app, client, h, admin):
    name = client.post("/admin/backups", headers=h).get_json()["backup"]["name"]
    t, _ = token(client, h)
    client.post(f"/admin/backups/{name}/restore", headers=h)
    assert app.test_client().get("/api/entities", headers=bearer(t)).status_code == 401


def test_a_token_revoked_long_ago_stays_revoked(app, client, h, admin):
    t, tid = token(client, h)
    undo = client.post(f"/account/tokens/{tid}/revoke", headers=h).get_json()["undo"]
    with app.app_context():
        row = db.session.get(ApiToken, tid)
        row.revoked_at = utcnow() - timedelta(minutes=11)
        db.session.commit()
    late = client.post(undo["url"], json=undo["body"], headers=h)
    assert late.status_code == 400 and "too long ago" in late.get_json()["error"]


def test_an_attachment_path_is_always_one_the_app_made(app, client, h, admin):
    box = make(client, h, "server", name="srv1")
    att = client.post(f"/api/entities/{box['id']}/attachments", headers=h, content_type="multipart/form-data",
                      data={"file": (io.BytesIO(b"hi"), "a.txt", "text/plain")}).get_json()["attachments"][0]
    from hyprvolt.core.models import Attachment
    with app.app_context():
        row = db.session.get(Attachment, att["id"])
        row.stored_as = app.config["DATA_DIR"] + "/.secret_key"
        db.session.commit()
    assert client.get(att["url"]).status_code == 404


def test_an_archive_with_links_is_refused(client, h, admin):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        info = tarfile.TarInfo("hyprvolt.db")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
        link = tarfile.TarInfo("attachments/aa/x")
        link.type, link.linkname = tarfile.SYMTYPE, "../../secrets.key"
        tar.addfile(link)
    resp = client.post("/admin/backups/upload", headers=h, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(out.getvalue()), "b.tar.gz")})
    assert resp.status_code == 400 and "links" in resp.get_json()["error"]


def test_writes_need_a_live_record(client, h, admin):
    domain = make(client, h, "domain", name="example.net")
    rec = client.post(f"/network/domains/{domain['id']}/records", json={"name": "www", "type": "A",
                                                                          "value": "10.0.0.1"}, headers=h).get_json()
    title = make(client, h, "software", name="Debian")
    host = make(client, h, "server", name="srv1")
    inst = client.post("/software/installations", json={"software_id": title["id"], "host_id": host["id"]},
                       headers=h).get_json()["installation"]
    client.post(f"/network/devices/{host['id']}/ports", json={"prefix": "eth", "first": 0, "last": 1}, headers=h)
    ports = client.get(f"/network/devices/{host['id']}/ports").get_json()["ports"]
    cable = client.post("/network/cables", json={"port_id": ports[0]["id"], "other_id": ports[1]["id"]},
                        headers=h).get_json()["cable"]
    client.post(f"/api/entities/{domain['id']}/delete", headers=h)
    client.post(f"/api/entities/{host['id']}/delete", headers=h)
    assert client.post(f"/network/records/{rec['record']['id']}/delete", headers=h).status_code == 404
    assert client.post(f"/software/installations/{inst['id']}/delete", headers=h).status_code == 404
    assert client.post("/software/installations/edit", json={"installation_id": inst["id"], "version": "x"},
                       headers=h).status_code == 404
    assert client.post(f"/network/cables/{cable['id']}/delete", headers=h).status_code == 404
    assert client.post("/network/ports/edit", json={"port_id": ports[0]["id"], "name": "x"},
                       headers=h).status_code == 404
    # Nonsense ids are a 404 or a 400, never a server error.
    for url, body in (("/network/cables", {"port_id": "x", "other_id": [1]}),
                      ("/software/installations/edit", {"installation_id": "x"}),
                      ("/vault/secrets/edit", {"secret_id": [1]})):
        assert client.post(url, json=body, headers=h).status_code in (400, 404), url


def test_an_import_refuses_a_field_the_type_lacks(client, h, admin):
    resp = client.post("/import/upload", headers=h, content_type="multipart/form-data",
                       data={"type": "server", "file": (io.BytesIO(b"name\nsrv1\n"), "x.csv")})
    body = {"token": __import__("re").search(r'name="token" value="([^"]+)"', resp.get_json()["html"]).group(1),
            "type": "server", "col0": "f.nonexistent", "match": "none"}
    bad = client.post("/import/check", json=body, headers=h)
    assert bad.status_code == 400 and "don't have" in bad.get_json()["error"]


def test_a_secret_links_only_to_the_web(client, h, admin):
    server = make(client, h, "server", name="srv1")
    bad = client.post(f"/vault/entities/{server['id']}/secrets",
                      json={"name": "x", "value": "y", "url": "javascript:alert(1)"}, headers=h)
    assert bad.status_code == 400 and "http" in bad.get_json()["error"]


def test_a_new_password_ends_the_other_sessions(app, client, h, admin):
    other = app.test_client()
    tok = token_for(other)
    other.post("/login", data={"_csrf": tok, "username": "admin@example.com", "password": "password1",
                               "remember": "on"})
    assert other.get("/api/entities", headers={"Accept": "application/json"}).status_code == 200
    resp = client.post("/account/password", json={"current": "password1", "new": "password2"}, headers=h)
    assert resp.status_code == 200
    assert client.get("/api/entities", headers={"Accept": "application/json"}).status_code == 200   # this one stays
    assert other.get("/api/entities", headers={"Accept": "application/json"}).status_code == 401    # that one ends
    assert client.post("/account/tokens", json={"name": "x"}, headers=h).status_code == 200         # CSRF kept
