"""Entities through the JSON API: the write path, history, tags, custom
fields, archive, delete with Undo, the purge, and who may do what."""
from hyprvolt.models import set_setting

from .conftest import make


def test_create_read_and_slug(client, h, admin):
    g = make(client, h, name="Blue Box", tags="lab, Prod", **{"f.color": "blue"}, notes="Under the desk.")
    assert g["slug"] == "blue-box" and g["fields"] == {"color": "blue", "battery": None}
    assert g["tags"] == ["lab", "Prod"] and g["status"] == "active"
    again = make(client, h, name="Blue box")
    assert again["slug"] == "blue-box-2"
    got = client.get(f"/api/entities/{g['id']}").get_json()["entity"]
    assert got["notes"] == "Under the desk." and got["type_label"] == "Gadget"


def test_names_statuses_and_slugs_are_checked(client, h, admin):
    assert "name" in client.post("/api/entities", json={"type": "gadget", "name": " "}, headers=h).get_json()["error"]
    bad = client.post("/api/entities", json={"type": "gadget", "name": "x", "status": "melted"}, headers=h)
    assert bad.status_code == 400 and "Active" in bad.get_json()["error"]
    make(client, h, name="One", slug="taken")
    clash = client.post("/api/entities", json={"type": "gadget", "name": "Two", "slug": "taken"}, headers=h)
    assert "taken by One" in clash.get_json()["error"]
    assert client.post("/api/entities", json={"type": "nothing", "name": "x"}, headers=h).status_code == 400


def test_edits_write_history_with_old_and_new_values(client, h, admin):
    g = make(client, h, name="Box", **{"f.color": "red"})
    client.post(f"/api/entities/{g['id']}", json={"name": "Big box", "fields": {"color": "green"}}, headers=h)
    # Saving the same values again changes nothing and logs nothing.
    client.post(f"/api/entities/{g['id']}", json={"name": "Big box", "fields": {"color": "green"}}, headers=h)
    history = client.get(f"/api/entities/{g['id']}/history").get_json()["history"]
    assert [e["action"] for e in history] == ["edited", "created"]
    changes = {c["label"]: (c["old"], c["new"]) for c in history[0]["changes"]}
    assert changes == {"Name": ("Box", "Big box"), "Color": ("red", "green")}
    assert history[0]["user"] == "Ada"


def test_tags_are_shared_and_case_insensitive(client, h, admin):
    make(client, h, name="A", tags=["Prod"])
    make(client, h, name="B", tags="prod, lab")
    tags = {t["name"]: t["count"] for t in client.get("/api/tags").get_json()["tags"]}
    assert tags == {"lab": 1, "Prod": 2}
    assert len(client.get("/api/entities?tag=PROD").get_json()["entities"]) == 2


def test_archive_and_undo(client, h, admin):
    g = make(client, h, name="Old box")
    resp = client.post(f"/api/entities/{g['id']}/archive", json={"archived": True}, headers=h).get_json()
    assert resp["entity"]["archived"]
    assert client.get("/api/entities").get_json()["entities"] == []
    assert len(client.get("/api/entities?archived=1").get_json()["entities"]) == 1
    undo = resp["undo"]
    client.post(undo["url"], json=undo["body"], headers=h)
    assert not client.get(f"/api/entities/{g['id']}").get_json()["entity"]["archived"]


def test_delete_is_undone_with_the_same_id(client, h, admin):
    g = make(client, h, name="Box", tags="lab")
    resp = client.post(f"/api/entities/{g['id']}/delete", headers=h).get_json()
    assert client.get("/api/entities").get_json()["entities"] == []
    assert client.post(f"/api/entities/{g['id']}", json={"name": "x"}, headers=h).status_code == 404
    client.post(resp["undo"]["url"], json=resp["undo"]["body"], headers=h)
    back = client.get(f"/api/entities/{g['id']}").get_json()["entity"]
    assert back["name"] == "Box" and back["tags"] == ["lab"] and not back["deleted"]
    actions = [e["action"] for e in client.get(f"/api/entities/{g['id']}/history").get_json()["history"]]
    assert actions == ["restored", "deleted", "created"]


def test_the_purge_removes_deleted_records_for_good(app, client, h, admin):
    keep = make(client, h, name="Keep")
    gone = make(client, h, name="Gone")
    client.post(f"/api/entities/{gone['id']}/delete", headers=h)
    from hyprvolt.core.records import purge
    from hyprvolt.models import db
    with app.app_context():
        assert purge(older_than_days=1) == 0      # too recent
        assert purge(older_than_days=0) == 1
        db.session.commit()
    assert client.get(f"/api/entities/{gone['id']}").status_code == 404
    assert client.get(f"/api/entities/{keep['id']}").status_code == 200
    # The history outlives it.
    from hyprvolt.core.models import AuditLog
    with app.app_context():
        assert [r.action for r in AuditLog.query.filter_by(entity_id=gone["id"]).order_by(AuditLog.id)] == \
            ["created", "deleted", "purged"]


def test_the_worker_runs_the_purge_job(app, client, h, admin):
    from hyprvolt.worker import run_once
    assert "core.purge" in run_once(app)
    assert run_once(app) == {}            # not due again for an hour


def test_viewers_read_and_editors_write(client, h, admin, viewer, editor):
    g = make(client, h, name="Box")
    other, oh = editor
    assert other.post(f"/api/entities/{g['id']}", json={"name": "Edited"}, headers=oh).status_code == 200
    assert other.post("/api/custom-fields", json={"entity_type": "gadget", "label": "X"}, headers=oh).status_code == 403


def test_a_viewer_cannot_write(client, h, admin, viewer):
    g = make(client, h, name="Box")
    other, oh = viewer
    assert other.get(f"/api/entities/{g['id']}").status_code == 200
    for url in ("/api/entities", f"/api/entities/{g['id']}", f"/api/entities/{g['id']}/archive",
                f"/api/entities/{g['id']}/delete", f"/api/entities/{g['id']}/restore"):
        assert other.post(url, json={"type": "gadget", "name": "x"}, headers=oh).status_code == 403, url


def test_a_turned_off_module_hides_its_records(app, client, h, admin):
    g = make(client, h, name="Box")
    with app.app_context():
        set_setting("module:example:enabled", "0")
    assert client.get(f"/api/entities/{g['id']}").status_code == 404
    assert client.post("/api/entities", json={"type": "gadget", "name": "x"}, headers=h).status_code == 400
    with app.app_context():
        set_setting("module:example:enabled", "1")
    assert client.get(f"/api/entities/{g['id']}").get_json()["entity"]["name"] == "Box"


def test_custom_fields(client, h, admin):
    made = client.post("/api/custom-fields", json={"entity_type": "gadget", "label": "Purchase price",
                                                   "kind": "number"}, headers=h).get_json()["field"]
    assert made["key"] == "purchase_price"
    sel = client.post("/api/custom-fields", json={"entity_type": "gadget", "label": "Owner", "kind": "select",
                                                  "options": "Ops\nDev"}, headers=h).get_json()["field"]
    assert sel["options"] == ["Ops", "Dev"]
    bad = client.post("/api/entities", json={"type": "gadget", "name": "x", "c.purchase_price": "lots"}, headers=h)
    assert "number" in bad.get_json()["error"]
    g = make(client, h, name="Box", custom={"purchase_price": "129.50", "owner": "Ops"})
    assert g["custom"] == {"purchase_price": 129.5, "owner": "Ops"}
    # Custom values are searchable.
    assert [e["id"] for e in client.get("/api/entities?q=129.5").get_json()["entities"]] == [g["id"]]

    resp = client.post(f"/api/custom-fields/{sel['id']}/delete", headers=h).get_json()
    assert "owner" not in client.get(f"/api/entities/{g['id']}").get_json()["entity"]["custom"]
    client.post(resp["undo"]["url"], json=resp["undo"]["body"], headers=h)
    assert client.get(f"/api/entities/{g['id']}").get_json()["entity"]["custom"]["owner"] == "Ops"


def test_custom_field_kinds_are_limited(client, h, admin):
    resp = client.post("/api/custom-fields", json={"entity_type": "gadget", "label": "X", "kind": "ref"}, headers=h)
    assert resp.status_code == 400


def test_search_matches_literally(client, h, admin):
    make(client, h, name="Findable 100%")
    assert len(client.get("/api/entities?q=0%25").get_json()["entities"]) == 1
    assert client.get("/api/entities?q=__").get_json()["entities"] == []


def test_an_admin_sets_when_a_record_was_created(client, h, admin, editor):
    doc = client.post("/api/entities", json={"type": "document", "name": "Manual", "created_at": "2019-05-02T09:30Z"},
                      headers=h).get_json()["entity"]
    assert doc["created_at"] == "2019-05-02T09:30:00Z"
    assert "Created <time" in client.get(f"/e/{doc['id']}/sheet").data.decode()
    client.post(f"/api/entities/{doc['id']}", json={"created_at": "2018-01-01T00:00Z"}, headers=h)
    history = client.get(f"/api/entities/{doc['id']}/history").get_json()["history"]
    assert history[0]["changes"][0]["label"] == "Created"
    other, oh = editor
    refused = other.post(f"/api/entities/{doc['id']}", json={"created_at": "2017-01-01T00:00Z"}, headers=oh)
    assert refused.status_code == 400 and "Only an admin" in refused.get_json()["error"]
    future = client.post(f"/api/entities/{doc['id']}", json={"created_at": "2999-01-01T00:00Z"}, headers=h)
    assert future.status_code == 400 and "future" in future.get_json()["error"]


def test_records_are_found_and_upserted_by_slug(client, h, admin):
    made = client.post("/api/entities/by-slug/ims-exporter", json={"type": "document", "name": "IMS Exporter",
                                                                  "f.body": "v1"}, headers=h).get_json()
    assert made["created"] is True and made["entity"]["slug"] == "ims-exporter"
    again = client.post("/api/entities/by-slug/ims-exporter", json={"type": "document", "name": "IMS Exporter",
                                                                   "f.body": "v2"}, headers=h).get_json()
    assert again["created"] is False and again["entity"]["id"] == made["entity"]["id"]
    assert again["entity"]["fields"]["body"] == "v2"
    got = client.get("/api/entities/by-slug/ims-exporter").get_json()["entity"]
    assert got["id"] == made["entity"]["id"]
    assert [e["id"] for e in client.get("/api/entities?slug=ims-exporter,nope").get_json()["entities"]] == [got["id"]]
    assert client.get("/api/entities/by-slug/nope").status_code == 404
    wrong = client.post("/api/entities/by-slug/ims-exporter", json={"type": "server"}, headers=h)
    assert wrong.status_code == 400 and "is a document" in wrong.get_json()["error"]
    assert client.post("/api/entities/by-slug/Bad Slug!", json={}, headers=h).status_code == 400
    client.post(f"/api/entities/{got['id']}/delete", headers=h)
    gone = client.post("/api/entities/by-slug/ims-exporter", json={"type": "document", "name": "x"}, headers=h)
    assert gone.status_code == 409 and "Restore it" in gone.get_json()["error"]
