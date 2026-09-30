"""The site setup guide: its steps from the modules, in order; a site walked
from the site itself out to its endpoints and cables; rows added, changed
and deleted one at a time, each saved at once; the buildings and rooms
tree; and who may use it."""
from hyprvolt.manifest import Module, SetupFinish, SetupKind, SetupStep
from hyprvolt.registry import Registry, validate

from .conftest import make


def entities(client, type_):
    """Every record of a type, each in full (with its fields)."""
    rows = client.get(f"/api/entities?type={type_}&per_page=200").get_json()["entities"]
    return [client.get(f"/api/entities/{e['id']}").get_json()["entity"] for e in rows]


def add(client, h, key, site=None, status=200, **values):
    """A step's blank row, filled in and added, as app.js does."""
    url = f"/site-setup/{key}/rows" + (f"?site={site}" if site else "")
    resp = client.post(url, json={"values": values}, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def change(client, h, key, row_id, name, value, site=None, status=200):
    """One field of a row, saved as it changes."""
    url = f"/site-setup/{key}/rows/{row_id}" + (f"?site={site}" if site else "")
    resp = client.post(url, json={"name": name, "value": value}, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def site_named(client, h, name):
    add(client, h, "site", **{"name": name})
    return next(e for e in entities(client, "site") if e["name"] == name)


def test_a_new_install_starts_with_what_the_guide_covers(client, h, admin):
    page = client.get("/site-setup").data.decode()
    assert "Let's document your first site" in page and "Start with the site" in page
    assert "Load a demo homelab instead" in page
    for group in ("Place", "Network", "Equipment", "What runs", "Endpoints"):
        assert f'<p class="guide-group">{group}</p>' in page
    assert "This guide covers the 5 main categories of a site" in page
    for plan in ("Site, buildings, rooms, and racks", "Vendors, internet connections, VLANs, and subnets",
                 "Network gear, servers, and storage", "Endpoints and cables"):
        assert f'<span class="guide-plan-steps">{plan}</span>' in page
    # Once something is recorded it is the guide's overview, run again.
    site_named(client, h, "Home")
    page = client.get("/site-setup").data.decode()
    assert "Set up a site, step by step" in page and "Load a demo homelab instead" not in page


def test_the_guide_has_the_page_to_itself(client, h, admin):
    """No sidebar, search or New menu around it: only the guide and a way out,
    the first time and every time after."""
    site_named(client, h, "Home")
    for url in ("/site-setup", "/site-setup/rooms", "/site-setup/done"):
        page = client.get(url).data.decode()
        assert 'class="guide-body"' in page and "Exit setup" in page, url
        assert 'id="sidebar"' not in page and 'id="new-btn"' not in page and "searchpill" not in page, url


def test_the_steps_run_from_the_site_to_the_cables(client, h, admin):
    page = client.get("/site-setup/site").data.decode()
    assert "Step 1 of" in page and "· Place" in page
    assert page.index("Buildings and rooms") < page.index("Internet connection") < page.index("Network gear") \
        < page.index("<span>Endpoints</span>") < page.index("<span>Cables</span>")


def test_a_site_is_set_up_step_by_step(client, h, admin):
    made = add(client, h, "site", **{"name": "Home", "f.city": "Springfield"})
    site = entities(client, "site")[0]
    assert made["go"].endswith(f"/site-setup/site?site={site['id']}")
    page = client.get(made["go"]).data.decode()
    assert 'value="Springfield"' in page and "data-row-new" not in page     # the site, to change
    basement = make(client, h, "room", name="Basement", location_id=site["id"])
    # Each vendor its own row, added one at a time and changed in place.
    add(client, h, "vendors", site["id"], name="Springfield Cable")
    add(client, h, "vendors", site["id"], name="Ubiquiti", **{"f.support_phone": "1-833-UBIQUITI"})
    isp = next(v for v in entities(client, "vendor") if v["name"] == "Springfield Cable")
    change(client, h, "vendors", isp["id"], "f.support_phone", "+1 555 010 0199", site["id"])
    page = client.get(f"/site-setup/vendors?site={site['id']}").data.decode()
    assert page.count("data-row ") == 2 and 'value="+1 555 010 0199"' in page and "data-row-new" in page
    # Where a record goes is chosen among the site's places, the site first.
    page = client.get(f"/site-setup/racks?site={site['id']}").data.decode()
    assert f'<option value="{basement["id"]}" >Basement</option>' in page.replace("selected", "")
    add(client, h, "racks", site["id"], name="Rack 1", location_id=basement["id"], **{"f.height_u": "24"})
    rack = entities(client, "rack")[0]
    assert rack["fields"]["height_u"] == 24 and rack["fields"]["numbering"] == "bottom"
    add(client, h, "internet", site["id"],
        **{"name": "Fiber", "location_id": site["id"], "s.supplier.vendor_id": isp["id"], "f.bandwidth": "1 Gb/s"})
    wan = entities(client, "network")[0]
    assert wan["fields"]["kind"] == "wan"
    page = client.get(f"/site-setup/internet?site={site['id']}").data.decode()
    assert f'<option value="{isp["id"]}" selected>Springfield Cable</option>' in page     # the provider, as saved
    add(client, h, "subnets", site["id"], **{"name": "LAN", "f.cidr": "10.0.20.0/24", "f.gateway": "10.0.20.1"})
    # The kind of each row: a switch is network gear of the kind switch.
    add(client, h, "gear", site["id"], **{"_kind": "3", "name": "sw1", "location_id": rack["id"],
                                          "s.addresses.list": "10.0.20.2"})
    add(client, h, "gear", site["id"], **{"_kind": "1", "name": "fw1", "location_id": rack["id"]})
    sw = next(e for e in entities(client, "network_device") if e["name"] == "sw1")
    assert sw["fields"]["kind"] == "switch" and any(e["name"] == "10.0.20.2" for e in entities(client, "ip_address"))
    # A row's kind changed: a router into a firewall, another type.
    router = next(e for e in entities(client, "network_device") if e["name"] == "fw1")
    change(client, h, "gear", router["id"], "_kind", "2", site["id"])
    assert entities(client, "firewall")[0]["name"] == "fw1"
    page = client.get(f"/site-setup/gear?site={site['id']}").data.decode()
    assert 'value="10.0.20.2"' in page                     # its address, as saved
    add(client, h, "endpoints", site["id"],
        **{"_kind": "0", "name": "desk-pc", "f.assigned_to": "Ada", "location_id": basement["id"]})
    add(client, h, "endpoints", site["id"], **{"_kind": "1", "name": "lp"})
    pc = entities(client, "workstation")[0]
    assert pc["fields"]["assigned_to"] == "Ada" and pc["location"]["id"] == basement["id"]
    # A printer has no Used by: its row shows that field off.
    page = client.get(f"/site-setup/endpoints?site={site['id']}").data.decode()
    assert page.split('data-name="lp"')[1].split("</fieldset>")[0].count("disabled") == 1
    # Cables: from a device to a device, each cabled as a whole; its label changed.
    page = client.get(f"/site-setup/cables?site={site['id']}").data.decode()
    assert f'value="device:{pc["id"]}"' in page
    add(client, h, "cables", site["id"], **{"from": f"device:{pc['id']}", "to": f"device:{sw['id']}", "label": "C1"})
    cable = client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"][0]["cable"]
    assert cable["to"] == "sw1" and cable["label"] == "C1"
    change(client, h, "cables", cable["id"], "label", "C9", site["id"])
    page = client.get(f"/site-setup/cables?site={site['id']}").data.decode()
    assert 'class="guide-locked-text">desk-pc</span>' in page and 'value="C9"' in page
    assert "delete it and connect it again" in change(client, h, "cables", cable["id"], "from", "x", site["id"],
                                                      status=400)["error"]
    done = client.get(f"/site-setup/done?site={site['id']}").data.decode()
    assert "Home is written down" in done and "2 recorded" in done


def test_rows_are_checked_one_at_a_time_and_deleted_with_undo(client, h, admin):
    site = site_named(client, h, "Home")
    add(client, h, "subnets", site["id"], **{"name": "Good", "f.cidr": "10.0.20.0/24"})
    bad = add(client, h, "subnets", site["id"], status=400, **{"name": "Bad", "f.cidr": "10.0.20"})
    assert "subnet with its prefix" in bad["error"]
    good = entities(client, "subnet")[0]
    assert [e["name"] for e in entities(client, "subnet")] == ["Good"]
    # A change that doesn't fit is refused and the record keeps what it had.
    assert "Give it a name" in change(client, h, "subnets", good["id"], "name", "", site["id"], status=400)["error"]
    assert entities(client, "subnet")[0]["name"] == "Good"
    gone = client.post(f"/site-setup/subnets/rows/{good['id']}/delete?site={site['id']}", headers=h).get_json()
    assert entities(client, "subnet") == []
    client.post(gone["undo"]["url"], json=gone["undo"]["body"], headers=h)
    assert entities(client, "subnet")[0]["name"] == "Good"
    # Only the step's own records: a site isn't a subnet.
    assert client.post(f"/site-setup/subnets/rows/{site['id']}/delete", headers=h).status_code == 404


def test_the_last_page_starts_the_site_runbook(client, h, admin):
    site = site_named(client, h, "Home")
    make(client, h, "room", name="Basement", location_id=site["id"])
    add(client, h, "subnets", site["id"], **{"name": "LAN", "f.cidr": "10.0.20.0/24"})
    done = client.get(f"/site-setup/done?site={site['id']}").data.decode()
    assert "Next, write it down" in done and "Start the site&#39;s runbook" in done
    resp = client.post(f"/site-setup/finish/runbook?site={site['id']}", headers=h)
    doc = entities(client, "document")[0]
    assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/documents?open={doc['id']}")
    room = entities(client, "room")[0]
    body = doc["fields"]["body"]
    assert doc["name"] == "Home runbook" and doc["status"] == "draft"
    assert f"## Place\n\n- Buildings and rooms: [[{room['slug']}]]" in body
    assert "## Network" in body and "## Who to call" in body and "## Backups and recovery" in body
    assert "Home runbook" in client.get(f"/e/{site['id']}/sheet?tab=documents").data.decode()
    # Once made, it is opened rather than made again.
    assert "Open the site&#39;s runbook" in client.get(f"/site-setup/done?site={site['id']}").data.decode()
    client.post(f"/site-setup/finish/runbook?site={site['id']}", headers=h)
    assert len(entities(client, "document")) == 1
    assert client.post("/site-setup/finish/nothing?site=1", headers=h).status_code == 404


def test_buildings_and_rooms_are_a_tree_of_the_site(client, h, admin):
    site = site_named(client, h, "Home")
    page = client.get(f"/site-setup/rooms?site={site['id']}").data.decode()
    assert "Places on-site that hold equipment." in page and "data-tree" in page and "data-rows-url" not in page
    assert f'data-node="{site["id"]}" data-type="site" data-name="Home"\n    data-accepts="building room"' in page
    assert "Continue</a>" in page and "Save and continue" not in page
    # Building 1 > Office 1 and Closet 1; a room holds nothing of this step.
    b1 = make(client, h, "building", name="Building 1", location_id=site["id"])
    office = make(client, h, "room", name="Office 1", location_id=b1["id"])
    closet = make(client, h, "room", name="Closet 1", location_id=site["id"])
    tree = client.get(f"/site-setup/rooms/tree?site={site['id']}").data.decode()
    order = [tree.index(f'data-name="{n}"') for n in ("Home", "Building 1", "Office 1", "Closet 1")]
    assert order == sorted(order)
    office_node = tree.split(f'data-node="{office["id"]}"')[1]
    assert 'data-accepts=""' in office_node.split("\n")[1] and "Add a room in Office 1" not in tree
    # Every place can be deleted; the dialog is told what else goes with it.
    assert 'aria-label="Delete Office 1"' in tree and 'aria-label="Delete Building 1"' in tree
    assert 'data-inside="1 room" data-holds="0"' in tree and 'aria-label="Delete Home"' not in tree
    # Moving a level: a room into the building; not into a room, and a
    # building not into a room either.
    client.post(f"/api/entities/{closet['id']}", json={"location_id": b1["id"]}, headers=h)
    assert client.get(f"/api/entities/{closet['id']}").get_json()["entity"]["location"]["id"] == b1["id"]
    for moving, into in ((closet, office), (b1, office)):
        wrong = client.post(f"/api/entities/{moving['id']}", json={"location_id": into["id"]}, headers=h)
        assert wrong.status_code == 400 and "can only be in a" in wrong.get_json()["error"]
    assert client.get("/site-setup/vendors/tree").status_code == 404


def test_deleting_a_building_takes_its_rooms_and_undo_brings_them_back(client, h, admin):
    site = site_named(client, h, "Home")
    b1 = make(client, h, "building", name="Building 1", location_id=site["id"])
    rooms = [make(client, h, "room", name=n, location_id=b1["id"]) for n in ("Office", "Lab")]
    make(client, h, "rack", name="Rack 1", location_id=rooms[0]["id"])
    tree = client.get(f"/site-setup/rooms/tree?site={site['id']}").data.decode()
    assert 'data-inside="2 rooms" data-holds="1"' in tree
    gone = client.post(f"/site-setup/rooms/tree/{b1['id']}/delete", headers=h).get_json()
    assert gone["deleted"] == 3 and entities(client, "room") == [] and entities(client, "building") == []
    assert len(entities(client, "rack")) == 1           # the rack stays, placed nowhere until Undo
    client.post(gone["undo"]["url"], json=gone["undo"]["body"], headers=h)
    assert {r["name"] for r in entities(client, "room")} == {"Office", "Lab"}
    assert entities(client, "rack")[0]["location"]["id"] == rooms[0]["id"]
    # Only a place of the step: a rack isn't one.
    rack = entities(client, "rack")[0]
    assert client.post(f"/site-setup/rooms/tree/{rack['id']}/delete", headers=h).status_code == 404


def test_choosing_the_site_or_a_new_one(client, h, admin):
    home, office = site_named(client, h, "Home"), site_named(client, h, "Office")
    page = client.get(f"/site-setup/site?site={home['id']}").data.decode()
    assert "data-go" in page and "A new site" in page and 'value="Home"' in page
    # A new site: the blank row, no site chosen.
    page = client.get("/site-setup/site?new=1").data.decode()
    assert "data-row-new" in page and 'value="Home"' not in page
    # Continue carries the chosen site on.
    page = client.get(f"/site-setup/site?site={office['id']}").data.decode()
    assert f'/site-setup/rooms?site={office["id"]}" data-rows-continue' in page


def test_viewers_cannot_use_it_and_editors_find_it(client, h, admin, viewer):
    other, oh = viewer
    assert other.get("/site-setup/site").status_code == 403
    assert other.post("/site-setup/site/rows", json={"values": {"name": "X"}}, headers=oh).status_code == 403
    assert "Set up a site, step by step" in client.get("/").data.decode()
    assert "Set up a site, step by step" not in other.get("/").data.decode()
    assert client.get("/site-setup/nothing").status_code == 404


def test_a_module_steps_are_checked():
    bad = Module(id="gadgets", name="Gadgets", setup=(
        SetupStep("things", "Things", "", 10, kinds=(SetupKind("Server", "server"),)),
        SetupStep("nothing", "Nothing", "", 20)))
    bad.setup_finish = (SetupFinish("Bad Key", "x", "x", make=None),)
    problems = " ".join(validate(bad, Registry()))
    assert "is not a SetupFinish" in problems
    assert "makes 'server', not one of the module's types" in problems
    assert "needs either kinds of record or a save function" in problems
    own = Module(id="gizmos", name="Gizmos", setup=(SetupStep("bits", "Bits", "", 10, save=lambda *a: None),))
    assert "needs a rows function" in " ".join(validate(own, Registry()))


def test_a_new_install_is_dark_and_the_wizard_can_switch(app, client, csrf):
    setup = client.get("/setup").data.decode()
    assert 'data-theme-pref="dark"' in setup and 'id="theme-btn"' in setup
    # The choice made on the setup page is the admin's from then on.
    client.post("/setup", json={"username": "ada@example.com", "password": "password1", "theme": "light",
                                "worker_minutes": 0}, headers={"X-CSRF": csrf})
    guide = client.get("/site-setup").data.decode()
    assert 'data-theme-pref="light"' in guide and 'id="theme-btn"' in guide
    with app.app_context():
        from hyprvolt.models import User
        from hyprvolt.models import db
        assert User.query.first().theme == "light"
        later = User(username="x@example.com", role="viewer")
        later.set_password("password1")
        db.session.add(later)
        db.session.commit()
        assert later.theme == "dark"            # every new account starts dark
