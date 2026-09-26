"""The secrets vault: encryption at rest with a key outside the database,
the separate permission, every reveal in the history, and the key's care."""
import os
import stat

from cryptography.fernet import Fernet

from hyprvolt.models import User, db

from .conftest import make


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def add(client, h, entity_id, status=200, **body):
    data = {"name": "Root password", "kind": "password", "username": "root", "value": "hunter2", **body}
    return post(client, h, f"/vault/entities/{entity_id}/secrets", status, **data)


def test_a_secret_is_encrypted_with_a_key_outside_the_database(app, client, h, admin):
    server = make(client, h, "server", name="srv1")
    made = add(client, h, server["id"])["secret"]
    assert "value" not in made
    with app.app_context():
        from hyprvolt.modules.vault.models import Secret
        row = db.session.get(Secret, made["id"])
        assert "hunter2" not in row.ciphertext
        key = os.path.join(app.config["DATA_DIR"], "secrets.key")
        assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
        assert Fernet(open(key, "rb").read().strip()).decrypt(row.ciphertext.encode()) == b"hunter2"
    listed = client.get(f"/vault/entities/{server['id']}/secrets").get_json()["secrets"]
    assert [s["name"] for s in listed] == ["Root password"] and "value" not in listed[0]
    # Search never finds a secret's value.
    assert client.get("/api/entities?q=hunter2").get_json()["entities"] == []


def test_every_reveal_is_in_the_history(client, h, admin):
    server = make(client, h, "server", name="srv1")
    sid = add(client, h, server["id"])["secret"]["id"]
    assert post(client, h, f"/vault/secrets/{sid}/reveal")["value"] == "hunter2"
    line = client.get(f"/api/entities/{server['id']}/history").get_json()["history"][0]
    assert line["action"] == "revealed a secret" and line["user"] == "Ada" and line["changes"][0]["new"] == "Root password"
    tab = client.get(f"/e/{server['id']}/sheet?tab=secrets").data.decode()
    assert "Root password" in tab and "hunter2" not in tab and 'data-reveal="/vault/secrets/' in tab
    assert "Latest reveals" in client.get("/").data.decode()


def test_only_people_given_access_see_secrets(app, client, h, admin, editor):
    server = make(client, h, "server", name="srv1")
    sid = add(client, h, server["id"])["secret"]["id"]
    other, oh = editor
    sheet = other.get(f"/e/{server['id']}/sheet").data.decode()
    assert 'data-tab="secrets"' not in sheet
    assert other.get(f"/vault/entities/{server['id']}/secrets").status_code == 403
    assert other.post(f"/vault/secrets/{sid}/reveal", headers=oh).status_code == 403
    assert "Root password" not in other.get(f"/e/{server['id']}/sheet?tab=history").data.decode()
    assert all(not r["action"].endswith("a secret")
               for r in other.get(f"/api/entities/{server['id']}/history").get_json()["history"])
    # Given access, the editor sees and changes them.
    post(client, h, "/admin/users/2/secrets", allowed=True)
    assert other.post(f"/vault/secrets/{sid}/reveal", headers=oh).get_json()["value"] == "hunter2"
    post(other, oh, f"/vault/entities/{server['id']}/secrets", name="iDRAC", value="x")
    # A viewer with access reads but can't change.
    client.post("/admin/users/2/role", json={"role": "viewer"}, headers=h)
    assert other.post(f"/vault/secrets/{sid}/reveal", headers=oh).status_code == 200
    assert other.post(f"/vault/entities/{server['id']}/secrets", json={"name": "x", "value": "y"},
                      headers=oh).status_code == 403
    # Admins see secrets always; it can't be taken away from one.
    refused = client.post("/admin/users/1/secrets", json={"allowed": False}, headers=h)
    assert refused.status_code == 400 and "Admins always see secrets" in refused.get_json()["error"]
    with app.app_context():
        admin_user = db.session.get(User, 1)
        admin_user.can_see_secrets = False
        db.session.commit()
    assert client.post(f"/vault/secrets/{sid}/reveal", headers=h).status_code == 200
    # Made an admin, the editor sees them too, whatever the flag says.
    client.post("/admin/users/2/role", json={"role": "admin"}, headers=h)
    post(client, h, "/admin/users/2/secrets", 400, allowed=False)


def test_changing_and_removing_a_secret(client, h, admin):
    server = make(client, h, "server", name="srv1")
    sid = add(client, h, server["id"])["secret"]["id"]
    post(client, h, "/vault/secrets/edit", secret_id=sid, name="Root", value="")
    assert post(client, h, f"/vault/secrets/{sid}/reveal")["value"] == "hunter2"
    post(client, h, "/vault/secrets/edit", secret_id=sid, value="new-one")
    assert post(client, h, f"/vault/secrets/{sid}/reveal")["value"] == "new-one"
    assert "Enter the secret" in add(client, h, server["id"], 400, value="")["error"]
    assert "Give the secret a name" in add(client, h, server["id"], 400, name="")["error"]
    undo = post(client, h, f"/vault/secrets/{sid}/delete")["undo"]
    assert client.get(f"/vault/entities/{server['id']}/secrets").get_json()["secrets"] == []
    assert client.post(f"/vault/secrets/{sid}/reveal", headers=h).status_code == 404
    post(client, h, undo["url"], **undo["body"])
    assert post(client, h, f"/vault/secrets/{sid}/reveal")["value"] == "new-one"


def test_deleted_secrets_are_purged(app, client, h, admin):
    server = make(client, h, "server", name="srv1")
    sid = add(client, h, server["id"])["secret"]["id"]
    post(client, h, f"/vault/secrets/{sid}/delete")
    from datetime import timedelta

    from hyprvolt.modules.vault import views
    from hyprvolt.modules.vault.models import Secret
    with app.app_context():
        s = db.session.get(Secret, sid)
        s.deleted_at = s.deleted_at - timedelta(days=31)
        db.session.commit()
        assert views.purge() == 1


def test_the_key_can_come_from_the_environment(app, client, h, admin, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_KEY", key)
    server = make(client, h, "server", name="srv1")
    sid = add(client, h, server["id"])["secret"]["id"]
    assert not os.path.exists(os.path.join(app.config["DATA_DIR"], "secrets.key"))
    assert post(client, h, f"/vault/secrets/{sid}/reveal")["value"] == "hunter2"
    assert "environment variable" in client.get("/").data.decode()
    # Another key can't open it, and says so.
    monkeypatch.setenv("SECRETS_KEY", Fernet.generate_key().decode())
    refused = post(client, h, f"/vault/secrets/{sid}/reveal", 409)
    assert "can't be opened with the key in use" in refused["error"]
    assert "The secrets can't be read." in client.get("/").data.decode()
    monkeypatch.setenv("SECRETS_KEY", "not a key")
    assert "SECRETS_KEY is not a key" in add(client, h, server["id"], 400)["error"]


def test_the_secrets_commands(app, client, h, admin):
    runner = app.test_cli_runner()
    assert "not made yet" in runner.invoke(args=["secrets", "status"]).output
    server = make(client, h, "server", name="srv1")
    add(client, h, server["id"])
    out = runner.invoke(args=["secrets", "status"]).output
    assert "secrets.key" in out and "Secrets: 1" in out and "opens all of them" in out
    Fernet(runner.invoke(args=["secrets", "new-key"]).output.strip().encode())
    backup = runner.invoke(args=["backup", str(app.config["DATA_DIR"]) + "/b.tar.gz"])
    assert backup.exit_code == 0 and "not in the backup, on purpose" in backup.output
    import tarfile
    with tarfile.open(str(app.config["DATA_DIR"]) + "/b.tar.gz") as tar:
        assert not any("secrets.key" in n for n in tar.getnames())
