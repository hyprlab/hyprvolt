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
    for plan in ("Site, buildings, rooms, racks, and vendors", "Internet connections, VLANs, subnets, and wireless networks",
                 "Network gear, servers, and storage", "Endpoints, UPSes, and cables"):
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


def test_every_step_says_what_goes_there_and_why(app, client, h, admin):
    with app.app_context():
        from hyprvolt.registry import current as registry
        steps = registry().setup_steps()
    assert steps and all(s.help for s in steps)
    site = site_named(client, h, "Home")
    for s in steps:
        page = client.get(f"/site-setup/{s.key}?site={site['id']}").data.decode()
        assert f'popovertarget="guide-help-{s.key}"' in page and "What goes here" in page, s.key
    vendors = client.get(f"/site-setup/vendors?site={site['id']}").data.decode()
    assert "a Usenet provider or an indexer" in vendors and "Logins and API keys go in Secrets" in vendors


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
    # A saved row is folded to its name, and opens to be changed.
    assert page.count('class="guide-row is-collapsed"') == 2
    assert 'aria-expanded="false"' in page and '<span class="guide-row-title" data-row-title>Ubiquiti</span>' in page
    # Where a record goes is chosen among the site's places, the site first.
    page = client.get(f"/site-setup/racks?site={site['id']}").data.decode()
    assert f'<option value="{basement["id"]}" >Basement (room)</option>' in page.replace("selected", "")
    assert f'<option value="{site["id"]}" >Home (site)</option>' in page.replace("selected", "")
    add(client, h, "racks", site["id"], name="Rack 1", location_id=basement["id"], **{"f.height_u": "24"})
    rack = entities(client, "rack")[0]
    assert rack["fields"]["height_u"] == 24 and rack["fields"]["numbering"] == "bottom"
    add(client, h, "internet", site["id"],
        **{"name": "Fiber", "location_id": site["id"], "s.supplier.vendor_id": isp["id"], "f.download": "1000",
           "f.upload": "40"})
    wan = entities(client, "network")[0]
    assert wan["fields"]["kind"] == "wan"
    page = client.get(f"/site-setup/internet?site={site['id']}").data.decode()
    assert f'<option value="{isp["id"]}" selected>Springfield Cable</option>' in page     # the provider, as saved
    # Dynamic or Static: the static line's fields only while the switch is on.
    new_row = page.split("data-row-new")[1]
    assert 'name="f.static_ip" value="0" checked' in new_row and "<span>Static</span>" in new_row
    assert 'data-when="f.static_ip" data-when-is="1" hidden><span class="field-label">Static IP' in new_row
    # Each part on its own line: the speeds, the switch, the static fields (the
    # line break hidden with them).
    assert new_row.count('class="guide-break"') == 3
    assert '<span class="guide-break" aria-hidden="true" data-when="f.static_ip" data-when-is="1" hidden>' in new_row
    change(client, h, "internet", wan["id"], "f.static_ip", True, site["id"])
    change(client, h, "internet", wan["id"], "f.public_ips", "203.0.113.26", site["id"])
    assert change(client, h, "internet", wan["id"], "f.netmask", "/29", site["id"])["value"] == "255.255.255.248"
    page = client.get(f"/site-setup/internet?site={site['id']}").data.decode()
    # Every row its own form, so each row's Dynamic or Static is its own.
    assert page.count("data-row-form") == page.count("data-row ") + page.count("data-row-new")
    saved = page.split("data-row-new")[0]
    assert 'data-when="f.static_ip" data-when-is="1"><span class="field-label">Static IP' in saved
    add(client, h, "subnets", site["id"], **{"name": "LAN", "f.cidr": "10.0.20.0/24", "f.gateway": "10.0.20.1"})
    # The kind of each row: a switch is network gear of the kind switch.
    lan = entities(client, "subnet")[0]
    add(client, h, "gear", site["id"], **{"_kind": "3", "name": "sw1", "location_id": rack["id"],
                                          "s.addresses.list": "10.0.20.2", "s.networks.list": str(lan["id"])})
    rels = client.get(f"/api/entities/{lan['id']}/relationships").get_json()["relationships"]
    assert [(r["label"], r["other"]["name"]) for r in rels] == [("is carried by", "sw1")]
    add(client, h, "gear", site["id"], **{"_kind": "1", "name": "fw1", "location_id": rack["id"]})
    # The Internet connection column: only in a modem's, router's or firewall's row.
    page = client.get(f"/site-setup/gear?site={site['id']}").data.decode()
    assert 'data-when="_kind" data-when-is="0 1 2"><span class="field-label">Internet connection' in page
    assert f'<option value="{wan["id"]}" >Fiber</option>' in page.replace("selected", "")
    switch_row = page.split('data-name="sw1"')[1].split("</fieldset>")[0]
    assert 'data-when="_kind" data-when-is="0 1 2" hidden>' in switch_row
    # A wireless bridge's other end: only in a bridge's row.
    assert 'data-when="_kind" data-when-is="6" hidden><span class="field-label">Other end' in page.split("data-row-new")[1]
    # Wireless networks, then the gear that broadcasts them, ticked in its row.
    add(client, h, "wifi", site["id"], **{"name": "home", "f.security": "wpa3", "f.bands": "5"})
    home = entities(client, "wifi")[0]
    add(client, h, "gear", site["id"], **{"_kind": "4", "name": "ap1", "s.wifi.list": str(home["id"])})
    ap = entities(client, "access_point")[0]
    page = client.get(f"/site-setup/gear?site={site['id']}").data.decode()
    ap_row = page.split('data-name="ap1"')[1].split("</fieldset>")[0]
    assert f'value="{home["id"]}" data-multi-item checked' in ap_row
    sw_row = page.split('data-name="sw1"')[1].split("</fieldset>")[0]
    assert f'value="{lan["id"]}" data-multi-item checked' in sw_row          # the networks it carries
    assert f'value="{home["id"]}" data-multi-item' in sw_row.split('data-when-is="0 1 4 5 6" hidden>')[-1]
    change(client, h, "gear", ap["id"], "s.wifi.list", "", site["id"])
    assert not client.get(f"/api/entities/{home['id']}/relationships").get_json()["relationships"]
    # A UPS ticks what it powers, from this site's equipment only.
    away = site_named(client, h, "Cabin")
    add(client, h, "servers", away["id"], **{"_kind": "0", "name": "cabin-srv", "location_id": away["id"]})
    page = client.get(f"/site-setup/ups?site={site['id']}").data.decode()
    assert '<span class="multi-group">Network gear</span>' in page and "cabin-srv" not in page
    sw1 = next(e for e in entities(client, "network_device") if e["name"] == "sw1")
    add(client, h, "ups", site["id"], **{"name": "ups1", "f.capacity_va": "1500", "s.powers.list": str(sw1["id"])})
    rels = client.get(f"/api/entities/{sw1['id']}/relationships").get_json()["relationships"]
    assert [r["other"]["name"] for r in rels if r["label"] == "powered by"] == ["ups1"]
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
    add(client, h, "endpoints", site["id"], **{"_kind": "2", "name": "phone1", "f.assigned_to": "Ada",
                                               "f.extension": "104"})
    phone = entities(client, "ip_phone")[0]
    add(client, h, "endpoints", site["id"], **{"_kind": "3", "name": "cam1"})
    assert entities(client, "ip_camera")[0]["name"] == "cam1"
    assert phone["fields"]["extension"] == "104" and phone["fields"]["assigned_to"] == "Ada"
    # A printer has no Used by: its row shows that field off. Extension is only in an IP phone's row.
    page = client.get(f"/site-setup/endpoints?site={site['id']}").data.decode()
    rows = {n: page.split(f'data-name="{n}"')[1].split("</fieldset>")[0] for n in ("lp", "desk-pc", "phone1")}
    assert rows["lp"].count("disabled") == 2     # Used by, and the hidden Extension
    assert [f'data-when-is="2" hidden><span class="field-label">Extension' in rows[n] for n in rows] == [True, True, False]
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
    from hyprvolt.manifest import EntityType, Field
    fills = Module(id="fills", name="Fills", types=(EntityType("thing", "Thing", "Things", detail=object, fields=(
        Field("name2", "Name", prefills=("x",)),)),))
    assert "fills in other fields from a subnet" in " ".join(validate(fills, Registry()))
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


def test_a_hypervisor_row_takes_its_servers_address(client, h, admin):
    site = site_named(client, h, "Home")
    add(client, h, "servers", site["id"], **{"_kind": "0", "name": "srv1", "s.addresses.list": "10.0.20.21"})
    srv = entities(client, "server")[0]
    page = client.get(f"/site-setup/hypervisors?site={site['id']}").data.decode()
    assert "Management IP" in page and "iDRAC, iLO or IPMI" in page
    add(client, h, "hypervisors", site["id"], **{"name": "pve1", "f.host": str(srv["id"])})
    pve = entities(client, "hypervisor")[0]
    got = change(client, h, "hypervisors", pve["id"], "s.addresses.list", "10.0.20.21", site["id"])
    assert got["notices"] == ["10.0.20.21 moved from the server srv1 to the hypervisor pve1 running on it."]
    servers = client.get(f"/site-setup/servers?site={site['id']}").data.decode()
    assert 'name="s.addresses.list" value="10.0.20.21"' not in servers
    assert 'name="s.hypervisor.address" value="10.0.20.21"' in servers     # its hypervisor's, shown on its row


def test_a_server_ticked_as_running_a_hypervisor_makes_and_links_one(client, h, admin):
    site = site_named(client, h, "Home")
    page = client.get(f"/site-setup/servers?site={site['id']}").data.decode()
    new_row = page.split("data-row-new")[1]
    # Its platform and management address wait for the box; the IP's label changes with it.
    assert 'data-when="s.hypervisor.on" data-when-is="1" hidden><span class="field-label">Hypervisor' in new_row
    assert 'data-relabel-to="BMC IP (iDRAC, iLO)" data-relabel-from="IP address">IP address<' in new_row
    got = add(client, h, "servers", site["id"], **{"_kind": "0", "name": "srv1", "s.addresses.list": "10.0.20.21",
                                                    "s.hypervisor.on": "1", "s.hypervisor.platform": "proxmox",
                                                    "s.hypervisor.address": "10.0.20.21"})
    assert "Added the hypervisor srv1, running on the server srv1." in got["notices"]
    ip = entities(client, "ip_address")[0]
    hyp = entities(client, "hypervisor")[0]
    srv = entities(client, "server")[0]
    assert hyp["name"] == "srv1" and hyp["fields"]["platform"] == "proxmox" and hyp["fields"]["host"] == srv["id"]
    assert ip["fields"]["assigned"] == hyp["id"]          # the management address is the hypervisor's
    page = client.get(f"/site-setup/servers?site={site['id']}").data.decode()
    row = page.split('data-name="srv1"')[1].split("</fieldset>")[0]
    assert ">BMC IP (iDRAC, iLO)<" in row and 'data-confirm-off="Delete its hypervisor?"' in row
    assert 'name="s.hypervisor.address" value="10.0.20.21"' in row
    assert 'name="s.addresses.list" value=""' in row
    assert 'data-name="srv1"' in client.get(f"/site-setup/hypervisors?site={site['id']}").data.decode()
    # A NAS row has the box too, and its hypervisor is a host a VM can choose in the guide.
    add(client, h, "servers", site["id"], **{"_kind": "1", "name": "nas1", "s.hypervisor.on": "1",
                                              "s.hypervisor.platform": "truenas"})
    guests = client.get(f"/site-setup/guests?site={site['id']}").data.decode()
    new_host = guests.split("data-row-new")[1].split('name="f.host"')[1].split("</select>")[0]
    assert ">nas1" in new_host and ">srv1" in new_host
    # The platform changed from the server's row.
    change(client, h, "servers", srv["id"], "s.hypervisor.platform", "vmware", site["id"])
    assert entities(client, "hypervisor")[0]["fields"]["platform"] == "vmware"
    # Unticked with a VM on it: refused. Without: the hypervisor is deleted.
    add(client, h, "guests", site["id"], **{"_kind": "0", "name": "vm1", "f.host": str(hyp["id"])})
    # The box says so before it is unticked, instead of asking to delete.
    row = client.get(f"/site-setup/servers?site={site['id']}").data.decode().split('data-name="srv1"')[1]
    assert ('data-confirm-blocked="srv1 can&#39;t be deleted yet" data-confirm-blocked-text="vm1 runs on it. '
            'Move it to another hypervisor or delete it first."') in row
    got = change(client, h, "servers", srv["id"], "s.hypervisor.on", False, site["id"], status=400)
    assert "srv1 can't be deleted yet: vm1 runs on it." in got["error"]
    vm = entities(client, "vm")[0]
    client.post(f"/api/entities/{vm['id']}/delete", headers=h)
    row = client.get(f"/site-setup/servers?site={site['id']}").data.decode().split('data-name="srv1"')[1]
    assert "data-confirm-blocked" not in row.split("</fieldset>")[0]
    got = change(client, h, "servers", srv["id"], "s.hypervisor.on", False, site["id"])
    assert [e["name"] for e in entities(client, "hypervisor")] == ["nas1"]
    assert got["notices"] == ["Deleted the hypervisor srv1."]


def test_rows_are_grouped_by_kind_in_the_kinds_order(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    for kind, name in (("3", "a-switch"), ("0", "z-modem"), ("3", "b-switch"), ("4", "ap1")):
        resp = client.post("/site-setup/gear/rows", json={"values": {"_kind": kind, "name": name}}, headers=h)
        assert resp.status_code == 200, resp.get_json()
    page = client.get("/site-setup/gear").data.decode()
    order = [page.index(s) for s in ('guide-kind">Modems<', 'data-name="z-modem"', 'guide-kind">Switches<',
                                     'data-name="a-switch"', 'data-name="b-switch"', 'guide-kind">Access points<',
                                     'data-name="ap1"', 'guide-kind">Add another<', "data-row-new")]
    assert order == sorted(order)
    # A step that isn't grouped has no headings.
    assert "guide-kind" not in client.get("/site-setup/guests").data.decode()
