"""Backups and restores from Settings, no terminal needed: making them by
hand and on a schedule, downloading, uploading, checking and restoring, the
sign-outs a restore causes, and the secrets key kept apart."""
import io
import json
import os
import tarfile

from cryptography.fernet import Fernet

from .conftest import make, token_for


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def attach(client, h, entity_id, data):
    return client.post(f"/api/entities/{entity_id}/attachments", headers=h,
                       data={"file": (io.BytesIO(data), "notes.txt", "text/plain")},
                       content_type="multipart/form-data").get_json()["attachments"][0]


def names(client):
    return [e["name"] for e in client.get("/api/entities").get_json()["entities"]]


def test_a_backup_holds_the_database_and_the_files(app, client, h, admin):
    box = make(client, h, "server", name="srv1")
    attach(client, h, box["id"], b"hello")
    made = post(client, h, "/admin/backups")["backup"]
    assert made["kind"] == "manual" and made["records"] == 1 and made["attachments"] == 1
    listed = client.get("/admin/backups").get_json()
    assert [b["name"] for b in listed["backups"]] == [made["name"]]
    assert listed["folder"] == os.path.join(app.config["DATA_DIR"], "backups")
    resp = client.get(f"/admin/backups/{made['name']}")
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
    with tarfile.open(fileobj=io.BytesIO(resp.data)) as tar:
        members = tar.getnames()
        assert members[0] == "backup.json" and "hyprvolt.db" in members
        assert any(n.startswith("attachments/") for n in members)
        manifest = json.loads(tar.extractfile("backup.json").read())
        assert manifest["format"] == "hyprvolt-backup" and manifest["made_by"] == "Ada"
    assert "Backups" in client.get("/").data.decode() and made["name"] in client.get("/").data.decode()


def test_a_restore_brings_everything_back_and_can_be_undone(app, client, h, admin, second_user):
    box = make(client, h, "server", name="srv1")
    att = attach(client, h, box["id"], b"version one")
    name = post(client, h, "/admin/backups")["backup"]["name"]
    # Things change after the backup.
    client.post(f"/api/entities/{box['id']}/delete", headers=h)
    make(client, h, "server", name="srv2")
    attach(client, h, make(client, h, "server", name="srv3")["id"], b"later")
    assert sorted(names(client)) == ["srv2", "srv3"]
    check = post(client, h, f"/admin/backups/{name}/check")
    assert "1 record" in check["html"] and "except you" in check["html"]
    done = post(client, h, f"/admin/backups/{name}/restore")
    assert done["signed_out"] is False and done["before"].startswith("hyprvolt-before-restore-")
    # The admin who restored is still signed in, and sees the backup's state.
    assert names(client) == ["srv1"]
    assert client.get(att["url"]).data == b"version one"
    # Everyone else is signed out: their sign-in is from before.
    other, _ = second_user
    assert other.get("/api/entities", headers={"Accept": "application/json"}).status_code == 401
    # Restoring the backup made before the restore undoes it.
    post(client, h, f"/admin/backups/{done['before']}/restore")
    assert sorted(names(client)) == ["srv2", "srv3"]


def test_a_restore_signs_out_an_admin_the_backup_doesnt_know(app, client, h, admin):
    name = post(client, h, "/admin/backups")["backup"]["name"]
    # A second admin, made after the backup, restores it.
    post(client, h, "/admin/users", username="late@example.com", password="password1", role="admin")
    late = app.test_client()
    token = token_for(late)
    late.post("/login", data={"_csrf": token, "username": "late@example.com", "password": "password1"})
    lh = {"X-CSRF": token}
    check = post(late, lh, f"/admin/backups/{name}/check")
    assert "your account isn't an admin in it" in check["html"]
    assert post(late, lh, f"/admin/backups/{name}/restore")["signed_out"] is True
    assert late.get("/api/entities", headers={"Accept": "application/json"}).status_code == 401


def upload(client, h, data, name="backup.tar.gz"):
    return client.post("/admin/backups/upload", headers=h, data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def archive(members: dict) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_an_uploaded_backup_is_checked_first(app, client, h, admin):
    make(client, h, "server", name="srv1")
    good = client.get(f"/admin/backups/{post(client, h, '/admin/backups')['backup']['name']}").data
    resp = upload(client, h, good)
    assert resp.status_code == 200 and "Restore this backup" in resp.get_json()["html"]
    assert resp.get_json()["name"].startswith("hyprvolt-uploaded-")
    for data, words in ((b"not a tarball", "isn't a .tar.gz"),
                        (archive({"notes.txt": b"x"}), "has no hyprvolt.db"),
                        (archive({"../../etc/passwd": b"x", "hyprvolt.db": b"x"}), "outside its own folder"),
                        (archive({"backup.json": json.dumps({"app_version": "99.0.0"}).encode(),
                                  "hyprvolt.db": b"x"}), "newer than this one"),
                        (archive({"hyprvolt.db": b"not a database"}), "can't be read")):
        bad = upload(client, h, data)
        assert bad.status_code == 400 and words in bad.get_json()["error"], (words, bad.get_json())
    # Only the good one was kept.
    assert len(client.get("/admin/backups").get_json()["backups"]) == 2


def test_backups_are_deleted_with_undo(client, h, admin):
    name = post(client, h, "/admin/backups")["backup"]["name"]
    undo = post(client, h, f"/admin/backups/{name}/delete")["undo"]
    assert client.get("/admin/backups").get_json()["backups"] == []
    post(client, h, undo["url"])
    assert [b["name"] for b in client.get("/admin/backups").get_json()["backups"]] == [name]
    assert client.get("/admin/backups/..%2F..%2Fhyprvolt.db").status_code == 404


def test_automatic_backups_come_on_schedule_and_the_oldest_go(app, client, h, admin):
    from hyprvolt.core import backups
    from hyprvolt.models import set_setting
    with app.test_request_context():
        assert backups.scheduled() == 1                  # none yet: one now
        assert backups.scheduled() == 0                  # not due again for a day
        set_setting("backup_keep", "2")
        set_setting("backup_hours", "1")
        for _ in range(3):
            backups.make("auto")
        # Four automatic ones now; a pass keeps the newest two.
        assert len([b for b in backups.listing() if b["kind"] == "auto"]) == 4
        backups.scheduled()
        autos = [b for b in backups.listing() if b["kind"] == "auto"]
        assert len(autos) == 2
        set_setting("backup_hours", "0")
        before = len(backups.listing())
        backups.scheduled()
        assert len(backups.listing()) == before
    assert client.post("/admin/instance", json={"backup_hours": 1000}, headers=h).status_code == 400


def test_the_secrets_key_is_downloaded_and_put_back(app, client, h, admin, monkeypatch):
    server = make(client, h, "server", name="srv1")
    client.post(f"/vault/entities/{server['id']}/secrets", json={"name": "root", "value": "hunter2"}, headers=h)
    key = client.get("/vault/key").data.decode().strip()
    Fernet(key.encode())
    assert "Last downloaded" in client.get("/").data.decode()
    # A key from elsewhere is refused; the right one goes back.
    wrong = client.post("/vault/key", data={"key": Fernet.generate_key().decode()}, headers=h)
    assert wrong.status_code == 400 and "doesn't open the secrets here" in wrong.get_json()["error"]
    assert "isn't a secrets key" in client.post("/vault/key", data={"key": "nope"}, headers=h).get_json()["error"]
    os.remove(os.path.join(app.config["DATA_DIR"], "secrets.key"))
    assert client.post(f"/vault/secrets/1/reveal", headers=h).status_code == 409
    ok = client.post("/vault/key", headers=h, content_type="multipart/form-data",
                     data={"file": (io.BytesIO(key.encode() + b"\n"), "hyprvolt-secrets.key")})
    assert ok.status_code == 200
    assert client.post("/vault/secrets/1/reveal", headers=h).get_json()["value"] == "hunter2"
    monkeypatch.setenv("SECRETS_KEY", key)
    assert "SECRETS_KEY" in client.post("/vault/key", data={"key": key}, headers=h).get_json()["error"]


def test_only_admins_touch_backups(client, h, admin, editor):
    name = post(client, h, "/admin/backups")["backup"]["name"]
    other, oh = editor
    for url in ("/admin/backups", f"/admin/backups/{name}/restore", f"/admin/backups/{name}/delete",
                "/admin/backups/upload", "/vault/key"):
        assert other.post(url, headers=oh).status_code == 403, url
    assert other.get(f"/admin/backups/{name}").status_code == 403
    assert other.get("/vault/key").status_code == 403


def test_the_commands_share_the_archive(app, client, h, admin):
    make(client, h, "server", name="srv1")
    runner = app.test_cli_runner()
    path = os.path.join(app.config["DATA_DIR"], "cli.tar.gz")
    assert runner.invoke(args=["backup", path]).exit_code == 0
    with tarfile.open(path) as tar:
        assert tar.getnames()[0] == "backup.json"
    make(client, h, "server", name="srv2")
    result = runner.invoke(args=["restore", path])
    assert result.exit_code == 0 and "Restored 1 records" in result.output


def test_versions_compare_in_semver_order():
    from hyprvolt.core.backups import _version
    order = ["1.3.0", "1.3.1", "1.4.0-beta.1", "1.4.0-beta.2", "1.4.0-beta.10", "1.4.0", "2.0.0-beta.1", "2.0.0"]
    assert sorted(order, key=_version) == order
    assert _version("1.4.0") == _version("1.4.0") and _version(None) < _version("0.1.0")
