"""Expiry reminders: kept current by every save and by the worker, within
an admin-set window, shown on the dashboard and as the sidebar badge."""
from datetime import date, timedelta

from hyprvolt.models import set_setting

from .conftest import make


def days(n):
    return (date.today() + timedelta(days=n)).isoformat()


def due(client):
    page = client.get("/").data.decode()
    card = page.split('id="coming-up"')[1].split('<div class="card widget')[0]
    return card


def test_a_save_updates_the_reminders_at_once(client, h, admin):
    title = make(client, h, "software", name="Office")
    lic = make(client, h, "license", name="Suite", **{"f.software": title["id"], "f.renews": days(20)})
    assert ">Suite</a>" in due(client) and "Renews " + days(20) in due(client) and "in 20 days" in due(client)
    client.post(f"/api/entities/{lic['id']}", json={"f.renews": days(200)}, headers=h)
    assert ">Suite</a>" not in due(client)
    client.post(f"/api/entities/{lic['id']}", json={"f.renews": days(-5)}, headers=h)
    assert "5 days ago" in due(client)
    # Archived, deleted or given up: no reminder. Back again: the reminder too.
    client.post(f"/api/entities/{lic['id']}/archive", json={"archived": True}, headers=h)
    assert ">Suite</a>" not in due(client)
    client.post(f"/api/entities/{lic['id']}/archive", json={"archived": False}, headers=h)
    assert ">Suite</a>" in due(client)
    client.post(f"/api/entities/{lic['id']}", json={"status": "retired"}, headers=h)
    assert ">Suite</a>" not in due(client)
    client.post(f"/api/entities/{lic['id']}", json={"status": "active"}, headers=h)
    client.post(f"/api/entities/{lic['id']}/delete", headers=h)
    assert ">Suite</a>" not in due(client)
    client.post(f"/api/entities/{lic['id']}/restore", headers=h)
    assert ">Suite</a>" in due(client)


def test_every_kind_of_date_is_reminded_of_soonest_first(client, h, admin):
    make(client, h, "domain", name="example.net", **{"f.expires": days(40)})
    make(client, h, "contract", name="Internet", **{"f.ends": days(10)})
    make(client, h, "ups", name="ups1", **{"f.battery_due": days(60), "f.warranty_until": days(-30)})
    make(client, h, "server", name="old", status="disposed", **{"f.warranty_until": days(5)})
    card = due(client)
    order = [card.index(n) for n in (">ups1</a>", ">Internet</a>", ">example.net</a>")]
    assert order == sorted(order) and card.count(">ups1</a>") == 2 and ">old</a>" not in card
    assert "Battery due" in card and "Warranty ends" in card


def test_the_window_is_an_admin_setting(app, client, h, admin):
    make(client, h, "domain", name="example.net", **{"f.expires": days(40)})
    assert ">example.net</a>" in due(client)
    client.post("/admin/instance", json={"reminder_days": 30}, headers=h)
    assert ">example.net</a>" not in due(client) and "in the next 30 days" in due(client)
    assert client.post("/admin/instance", json={"reminder_days": 0}, headers=h).status_code == 400
    # The filters use it too.
    assert ">example.net<" not in client.get("/network?f=renewal&view=list").data.decode()
    # Time passing is the worker's: with the window set behind its back, the
    # next pass catches up.
    with app.app_context():
        set_setting("reminder_days", "60")
    assert ">example.net</a>" not in due(client)
    from hyprvolt.worker import run_once
    assert run_once(app, force=True)["core.reminders"] == 1
    assert ">example.net</a>" in due(client)


def test_the_sidebar_badge_counts_what_is_due(client, h, admin):
    make(client, h, "contract", name="Internet", **{"f.ends": days(10)})
    page = client.get("/hardware").data.decode()
    assert 'title="1 date coming up or just past">1<' in page
    client.post("/admin/modules/contacts", json={"enabled": False}, headers=h)
    assert "coming up or just past" not in client.get("/hardware").data.decode()


def test_past_renewals_count_as_soon_but_a_past_warranty_does_not(client, h, admin):
    title = make(client, h, "software", name="Office")
    make(client, h, "license", name="Suite", **{"f.software": title["id"], "f.renews": days(-10)})
    make(client, h, "server", name="srv1", **{"f.warranty_until": days(-10)})
    assert ">Suite<" in client.get("/software?f=renewal&view=list").data.decode()
    assert ">srv1<" not in client.get("/hardware?f=warranty_soon&view=list").data.decode()
    assert ">srv1<" in client.get("/hardware?f=warranty_over&view=list").data.decode()
