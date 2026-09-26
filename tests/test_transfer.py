"""CSV export of a filtered list, CSV import with column matching and a
check that saves nothing, and the JSON export of the whole instance."""
import csv
import io
import json
import os
import re
import time

from .conftest import make


def export(client, url):
    resp = client.get(url)
    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    return list(csv.reader(io.StringIO(resp.data.decode("utf-8-sig"))))


def upload(client, h, type_, text, status=200):
    resp = client.post("/import/upload", data={"type": type_, "file": (io.BytesIO(text.encode()), "x.csv")},
                       headers=h, content_type="multipart/form-data")
    assert resp.status_code == status, resp.get_json()
    got = resp.get_json()
    if status != 200:
        return got
    html = got["html"]
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    chosen = {}
    for m in re.finditer(r'<select name="(col\d+)"[^>]*>(.*?)</select>', html, re.S):
        sel = re.search(r'<option value="([^"]*)" selected>', m.group(2))
        chosen[m.group(1)] = sel.group(1) if sel else ""
    return {"token": token, "type": type_, "match": "none", **chosen, "html": html}


def body_of(step, **changes):
    return {k: v for k, v in {**step, **changes}.items() if k != "html"}


def test_a_list_exports_as_it_is_filtered(client, h, admin):
    site = make(client, h, "site", name="Home")
    make(client, h, "server", name="srv1", location_id=site["id"],
         **{"f.model": "R730xd", "f.ram_gb": 128, "f.kind": "rack", "f.price": 850.0}, tags="lab, prod")
    make(client, h, "server", name="=cmd()", **{"f.model": "-danger"})
    make(client, h, "nas", name="nas1")
    rows = export(client, "/export/hardware.csv?type=server&sort=name")
    header, body = rows[0], rows[1:]
    assert header[:7] == ["id", "type", "name", "slug", "status", "location", "tags"] and "Memory" in header
    by_name = {r[2]: dict(zip(header, r)) for r in body}
    assert set(by_name) == {"srv1", "'=cmd()"}
    srv = by_name["srv1"]
    assert (srv["Memory"], srv["Form factor"], srv["Price"], srv["location"], srv["tags"], srv["status"]) == \
        ("128", "Rack mount", "850", "Home", "lab, prod", "Deployed")
    assert by_name["'=cmd()"]["Model"] == "'-danger" and srv["link"].endswith(f"/e/{srv['id']}")
    only = export(client, "/export/hardware.csv?q=nas1")
    assert [r[2] for r in only[1:]] == ["nas1"]
    assert len(export(client, "/export/all.csv")) == 5
    assert client.get("/export/nothing.csv").status_code == 404
    assert client.get("/export/vault.csv").status_code == 404


def test_an_import_is_matched_checked_and_then_saved(client, h, admin):
    site = make(client, h, "site", name="Home lab")
    building = make(client, h, "building", name="House", location_id=site["id"])
    make(client, h, "room", name="Basement", location_id=building["id"])
    make(client, h, "room", name="Office", location_id=building["id"])
    text = ("Name,Model,Memory,Form factor,Where,Tags,Status,Warranty ends,Colour\n"
            "srv1,R730xd,128,Rack mount,Home lab > House > Basement,lab,Deployed,2027-01-31,red\n"
            "srv2,,64,tower,Office,,in stock,,\n"
            "srv3,,lots,,Attic,,,,\n")
    step = upload(client, h, "server", text)
    assert (step["col0"], step["col1"], step["col2"], step["col3"], step["col5"], step["col6"], step["col7"]) == \
        ("name", "f.model", "f.ram_gb", "f.kind", "tags", "status", "f.warranty_until")
    assert step["col4"] == "" and step["col8"] == "" and "3 rows to import as servers" in step["html"]
    step["col4"] = "location"
    checked = client.post("/import/check", json=body_of(step), headers=h).get_json()
    assert "2 to make" in checked["html"] and "1 with a problem" in checked["html"]
    assert "Row 4 · srv3" in checked["html"] and "No place is called “Attic”" in checked["html"]
    assert client.get("/api/entities?type=server").get_json()["entities"] == []       # the check saved nothing
    run = client.post("/import/run", json=body_of(step), headers=h).get_json()
    assert run["message"] == "Imported: 2 made, 1 left out"
    got = {e["name"]: client.get(f"/api/entities/{e['id']}").get_json()["entity"]
           for e in client.get("/api/entities?type=server").get_json()["entities"]}
    assert set(got) == {"srv1", "srv2"}
    assert got["srv1"]["location"]["name"] == "Basement" and got["srv1"]["fields"]["warranty_until"] == "2027-01-31"
    assert got["srv2"]["status"] == "in_stock" and got["srv2"]["fields"]["kind"] == "tower"
    history = client.get(f"/api/entities/{got['srv1']['id']}/history").get_json()["history"]
    assert history[-1]["action"] == "created" and history[-1]["user"] == "Ada"
    # The upload is gone once used.
    assert client.post("/import/run", json=body_of(step), headers=h).status_code == 400


def test_an_import_updates_records_with_the_same_name(client, h, admin):
    make(client, h, "server", name="srv1", **{"f.model": "Old", "f.ram_gb": 64})
    step = upload(client, h, "server", "name,model,memory\nSRV1,New,\nsrv9,,32\n")
    run = client.post("/import/run", json=body_of(step, match="name"), headers=h).get_json()
    assert run["created"] == 1 and run["updated"] == 1
    srv1 = [e for e in client.get("/api/entities?type=server&q=srv1").get_json()["entities"]][0]
    fields = client.get(f"/api/entities/{srv1['id']}").get_json()["entity"]["fields"]
    assert fields["model"] == "New" and fields["ram_gb"] == 64          # the empty cell left it alone


def test_an_export_imports_back_unchanged(client, h, admin):
    site = make(client, h, "site", name="Home")
    make(client, h, "server", name="srv1", location_id=site["id"], tags="lab",
         **{"f.model": "R730xd", "f.kind": "rack", "f.managed": None})
    rows = export(client, "/export/hardware.csv?type=server")
    text = io.StringIO()
    csv.writer(text).writerows(rows)
    step = upload(client, h, "server", text.getvalue())
    run = client.post("/import/run", json=body_of(step, match="name"), headers=h).get_json()
    assert run["created"] == 0 and run["updated"] == 0 and run["skipped"] == 0


def test_imports_of_named_fields_and_bad_files(client, h, admin):
    step = upload(client, h, "ip_address", "Address,Assigned to\n10.0.20.5,\n10.0.20.6,\n")
    assert step["col0"] == "f.address"
    assert client.post("/import/run", json=body_of(step), headers=h).get_json()["created"] == 2
    assert "no rows" in upload(client, h, "server", "", 400)["error"]
    assert "no rows under it" in upload(client, h, "server", "name\n", 400)["error"]
    assert "at most 5,000 rows" in upload(client, h, "server", "name\n" + "x\n" * 5001, 400)["error"]
    assert "kind of record" in upload(client, h, "spaceship", "name\nx\n", 400)["error"]
    step = upload(client, h, "server", "name\nsrv1\n")
    no_name = client.post("/import/check", json=body_of(step, col0=""), headers=h).get_json()
    assert "at least one column" in no_name["error"]
    # Semicolons, as a European spreadsheet writes them, are fine.
    step = upload(client, h, "server", "name;model\nsrv7;X1\n")
    assert step["col1"] == "f.model"


def test_only_editors_import(client, h, admin, viewer):
    other, oh = viewer
    assert other.post("/import/upload", data={"type": "server"}, headers=oh).status_code == 403
    assert other.get("/export/hardware.csv").status_code == 200
    assert 'id="import-modal"' not in other.get("/hardware").data.decode()
    assert 'id="import-modal"' in client.get("/hardware").data.decode()


def test_old_uploads_are_cleaned_up(app, client, h, admin):
    step = upload(client, h, "server", "name\nsrv1\n")
    path = os.path.join(app.config["DATA_DIR"], "imports", step["token"] + ".csv")
    old = time.time() - 2 * 24 * 3600
    os.utime(path, (old, old))
    from hyprvolt.core.transfer import cleanup
    with app.app_context():
        assert cleanup() == 1
    assert not os.path.exists(path)


def test_the_whole_instance_as_json(app, client, h, admin, editor):
    server = make(client, h, "server", name="srv1")
    client.post(f"/vault/entities/{server['id']}/secrets", json={"name": "root", "value": "hunter2"}, headers=h)
    resp = client.get("/admin/export.json")
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
    data = json.loads(resp.data)
    assert data["format"] == "hyprvolt-export" and data["version"] == 1
    assert [e["name"] for e in data["tables"]["entities"]] == ["srv1"]
    assert "password_hash" not in data["tables"]["users"][0]
    assert data["tables"]["vault_secrets"][0]["name"] == "root" and "ciphertext" not in data["tables"]["vault_secrets"][0]
    assert "hunter2" not in resp.data.decode() and "hardware_details" in data["tables"]
    other, _ = editor
    assert other.get("/admin/export.json").status_code == 403
    out = os.path.join(app.config["DATA_DIR"], "all.json")
    result = app.test_cli_runner().invoke(args=["export", out])
    assert result.exit_code == 0 and json.load(open(out))["tables"]["entities"][0]["name"] == "srv1"
