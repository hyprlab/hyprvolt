"""Maintenance and changes, and the date-and-time fields they rest on:
times typed and shown in the instance's time zone and stored in UTC, what a
window takes down, and every record's Changes tab."""
from datetime import timedelta

from .conftest import make


def fields(client, entity_id):
    return client.get(f"/api/entities/{entity_id}").get_json()["entity"]["fields"]


def link(client, h, source, target):
    resp = client.post("/api/relationships", json={"entity_id": source["id"], "direction": "out", "kind": "affects",
                                                   "other_id": target["id"]}, headers=h)
    assert resp.status_code == 200, resp.get_json()


def test_times_are_typed_and_shown_in_the_instance_time_zone(client, h, admin):
    assert client.post("/admin/instance", json={"time_zone": "America/Chicago"}, headers=h).status_code == 200
    bad = client.post("/admin/instance", json={"time_zone": "Mars/Olympus"}, headers=h)
    assert bad.status_code == 400 and "time zone" in bad.get_json()["error"]
    w = make(client, h, "maintenance", name="Upgrade", **{"f.starts": "2026-10-03T22:00", "f.ends": "2026-10-04T01:00"})
    # Chicago is five hours behind UTC in October: stored and sent as UTC.
    assert fields(client, w["id"])["starts"] == "2026-10-04T03:00Z"
    form = client.get(f"/e/{w['id']}/form").data.decode()
    assert 'type="datetime-local"' in form and 'value="2026-10-03T22:00"' in form
    assert 'value="2026-10-03T22:00"' in client.get(f"/e/{w['id']}/sheet").data.decode()
    # A time with an offset is taken as it says.
    client.post(f"/api/entities/{w['id']}", json={"f.ends": "2026-10-04T08:30Z"}, headers=h)
    assert fields(client, w["id"])["ends"] == "2026-10-04T08:30Z"
    # Another zone moves nothing that is stored, only how it reads.
    client.post("/admin/instance", json={"time_zone": "UTC"}, headers=h)
    assert 'value="2026-10-04T03:00"' in client.get(f"/e/{w['id']}/sheet").data.decode()
    wrong = client.post("/api/entities", json={"type": "maintenance", "name": "x", "f.starts": "soon",
                                               "f.ends": "2026-10-04T01:00"}, headers=h)
    assert wrong.status_code == 400 and "date and time" in wrong.get_json()["error"]
    backwards = client.post("/api/entities", json={"type": "maintenance", "name": "x", "f.starts": "2026-10-04T01:00",
                                                   "f.ends": "2026-10-03T22:00"}, headers=h)
    assert backwards.status_code == 400 and "end after it starts" in backwards.get_json()["error"]


def test_the_time_zone_starts_as_tz(app, client, h, admin, monkeypatch):
    from hyprvolt.core import clock
    monkeypatch.setenv("TZ", "Europe/Berlin")
    with app.app_context():
        assert clock.zone_name() == "Europe/Berlin"
    monkeypatch.setenv("TZ", "nonsense")
    with app.app_context():
        assert clock.zone_name() == "UTC"


def test_a_window_lists_what_goes_down_with_it(client, h, admin):
    host = make(client, h, "hypervisor", name="pve1")
    vm = make(client, h, "vm", name="docker1", **{"f.host": host["id"]})
    service = make(client, h, "service", name="Jellyfin", **{"f.host": vm["id"]})
    w = make(client, h, "maintenance", name="Kernel upgrade", **{"f.starts": "2030-10-03T22:00", "f.ends": "2030-10-04T01:00"})
    link(client, h, w, host)
    tab = client.get(f"/e/{w['id']}/sheet?tab=impact").data.decode()
    assert ">pve1</a>" in tab and ">docker1</a>" in tab and ">Jellyfin</a>" in tab and "runs 3 hours" in tab
    # The link carries no dependency: the host doesn't need the window.
    needs = client.get(f"/api/entities/{host['id']}/dependencies?direction=dependencies").get_json()["tree"]
    assert "Kernel upgrade" not in str(needs)
    client.post(f"/api/entities/{w['id']}", json={"f.impact": "none"}, headers=h)
    assert ">docker1</a>" not in client.get(f"/e/{w['id']}/sheet?tab=impact").data.decode()
    assert ">Kernel upgrade<" in client.get("/maintenance?f=upcoming&view=list").data.decode()
    assert ">Kernel upgrade<" not in client.get("/maintenance?f=now&view=list").data.decode()


def test_a_window_under_way_is_shown_on_the_dashboard(client, h, admin):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    w = make(client, h, "maintenance", name="Swap the switch",
             **{"f.starts": (now - timedelta(hours=1)).isoformat(), "f.ends": (now + timedelta(hours=1)).isoformat()})
    assert ">Swap the switch<" in client.get("/maintenance?f=now&view=list").data.decode()
    page = client.get("/").data.decode()
    assert ">Swap the switch</a>" in page and "under way" in page
    client.post(f"/api/entities/{w['id']}", json={"status": "canceled"}, headers=h)
    assert ">Swap the switch</a>" not in client.get("/").data.decode()


def test_a_change_is_recorded_from_what_it_affects(client, h, admin):
    server = make(client, h, "server", name="srv1")
    tab = client.get(f"/e/{server['id']}/sheet?tab=changes").data.decode()
    assert "No changes recorded" in tab and f'data-new-link="affects:{server["id"]}"' in tab
    form = client.get(f"/e/form?type=change&link=affects:{server['id']}").data.decode()
    assert f'name="link" value="affects:{server["id"]}"' in form
    ch = make(client, h, "change", name="Updated the BIOS", link=f"affects:{server['id']}", status="rolled_back",
              **{"f.kind": "upgrade"})
    assert fields(client, ch["id"])["at"]            # when left empty: now
    tab = client.get(f"/e/{server['id']}/sheet?tab=changes").data.decode()
    assert ">Updated the BIOS</a>" in tab and "Rolled back" in tab
    assert ">Updated the BIOS<" in client.get("/maintenance?f=trouble&view=list").data.decode()
    assert ">Updated the BIOS<" in client.get("/maintenance?f=recent&view=list").data.decode()
    gone = client.post("/api/entities", json={"type": "change", "name": "x", "link": "affects:99999"}, headers=h)
    assert gone.status_code == 400
    assert 'data-tab="changes"' not in client.get(f"/e/{ch['id']}/sheet").data.decode()


def test_changes_made_in_a_window_are_listed_in_it(client, h, admin):
    w = make(client, h, "maintenance", name="Upgrade", **{"f.starts": "2026-01-03T22:00", "f.ends": "2026-01-04T01:00"})
    make(client, h, "change", name="Upgraded pve1", **{"f.window": w["id"], "f.at": "2026-01-03T22:40"})
    tab = client.get(f"/e/{w['id']}/sheet?tab=impact").data.decode()
    assert ">Upgraded pve1</a>" in tab and "Ran from" in tab


def test_viewers_see_but_do_not_record(client, h, admin, viewer):
    server = make(client, h, "server", name="srv1")
    other, vh = viewer
    tab = other.get(f"/e/{server['id']}/sheet?tab=changes").data.decode()
    assert "No changes recorded" in tab and "Record a change" not in tab
    assert other.post("/api/entities", json={"type": "change", "name": "x"}, headers=vh).status_code == 403


def test_times_export_and_import_back_unchanged(client, h, admin):
    from .test_transfer import body_of, export, upload
    import csv
    import io
    client.post("/admin/instance", json={"time_zone": "Europe/Berlin"}, headers=h)
    make(client, h, "maintenance", name="Upgrade", **{"f.starts": "2026-10-03T22:00", "f.ends": "2026-10-04T01:00"})
    rows = export(client, "/export/maintenance.csv?type=maintenance")
    row = dict(zip(rows[0], rows[1]))
    assert row["Starts"] == "2026-10-03 22:00" and row["Ends"] == "2026-10-04 01:00"
    text = io.StringIO()
    csv.writer(text).writerows(rows)
    step = upload(client, h, "maintenance", text.getvalue())
    run = client.post("/import/run", json=body_of(step, match="name"), headers=h).get_json()
    assert run["created"] == 0 and run["updated"] == 0 and run["skipped"] == 0
