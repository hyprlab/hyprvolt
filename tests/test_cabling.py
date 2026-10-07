"""Suggest cables, in the site setup guide's Cables step: the cabling
worked out from the gear and where each is, checked, then added."""
import re

from .conftest import make


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def lab(client, h):
    """A house with a rack in the basement and an office; a den reached over
    MoCA; a garage over a wireless bridge."""
    site = make(client, h, "site", name="Home")
    house = make(client, h, "building", name="House", location_id=site["id"])
    basement = make(client, h, "room", name="Basement", location_id=house["id"])
    office = make(client, h, "room", name="Office", location_id=house["id"])
    den = make(client, h, "room", name="Den", location_id=house["id"])
    garage = make(client, h, "building", name="Garage", location_id=site["id"])
    rack = make(client, h, "rack", name="r1", location_id=basement["id"])

    def gear(name, kind, where, **more):
        return make(client, h, "network_device", name=name, location_id=where["id"], **{"f.kind": kind, **more})
    d = {"site": site}
    d["modem"] = gear("modem", "modem", rack)
    d["fw"] = make(client, h, "firewall", name="fw", location_id=rack["id"])
    d["core"] = gear("sw-core", "switch", rack, **{"f.ports": 24})
    d["sw-office"] = gear("sw-office", "switch", office, **{"f.ports": 8})
    d["moca1"] = gear("moca-basement", "moca", basement)
    d["moca2"] = gear("moca-den", "moca", den, **{"s.moca.other": d["moca1"]["id"]})
    d["br-house"] = gear("br-house", "bridge", basement)
    d["br-garage"] = gear("br-garage", "bridge", garage, **{"s.bridge.other": d["br-house"]["id"]})
    d["ext"] = gear("ext1", "extender", office)
    d["panel"] = gear("pp1", "patch_panel", rack)
    d["srv1"] = make(client, h, "server", name="srv1", location_id=rack["id"])
    d["desk"] = make(client, h, "workstation", name="desk-pc", location_id=office["id"])
    d["ap"] = make(client, h, "access_point", name="ap-office", location_id=office["id"])
    d["phone"] = make(client, h, "ip_phone", name="phone-den", location_id=den["id"])
    d["cam"] = make(client, h, "ip_camera", name="cam-garage", location_id=garage["id"])
    d["loose"] = make(client, h, "ip_camera", name="cam-loose")
    d["monitor"] = make(client, h, "peripheral", name="monitor", location_id=office["id"])
    d["lp"] = make(client, h, "printer", name="lp", location_id=office["id"])
    post(client, h, "/network/cables", device_id=d["lp"]["id"], other_device_id=d["sw-office"]["id"])
    return d


def suggest(client, h, site):
    html = post(client, h, "/network/cables/suggest", site=site["id"], back="/site-setup/cables")["html"]
    rows = {}
    for block in html.split('<li class="review-item">')[1:]:
        title = re.search(r"<span>([^<]+)</span>", block).group(1)
        rows[title] = {
            "i": re.search(r'name="use(\d+)"', block).group(1),
            "chip": re.search(r'<span class="chip[^"]*">([^<]+)</span>', block).group(1),
            "why": " ".join(re.search(r'<span class="review-why">(.*?)</span>', block, re.S).group(1).split()),
            "a": (re.search(r'name="a\d+">.*?<option value="([^"]+)" selected', block, re.S) or [None, ""])[1],
            "b": (re.search(r'name="b\d+">.*?<option value="([^"]+)" selected', block, re.S) or [None, ""])[1],
            "checked": "checked" in block.split("<span>")[0]}
    return html, rows


def test_the_cabling_is_worked_out_from_the_gear_and_where_it_is(client, h, admin):
    d = lab(client, h)
    html, rows = suggest(client, h, d["site"])
    # A MoCA pair works like a cable: no cable between the two adapters.
    assert set(rows) == {"modem to fw", "fw to sw-core", "moca-basement to sw-core",
                         "br-house to sw-core", "sw-office to sw-core", "srv1 to sw-core", "ap-office to sw-office",
                         "desk-pc to sw-office", "phone-den to moca-den", "cam-garage to br-garage", "cam-loose to sw-core"}
    # The backbone comes first, then what plugs into each switch and far end.
    assert html.index("The backbone") < html.index("Plugged into sw-core") < html.index("Plugged into moca-den")
    assert "the core switch" in rows["fw to sw-core"]["why"]
    assert "Garage" in rows["cam-garage to br-garage"]["why"] and rows["cam-garage to br-garage"]["chip"] == "Likely"
    assert "same room, Office" in rows["desk-pc to sw-office"]["why"]
    assert "same rack, r1" in rows["srv1 to sw-core"]["why"]
    # Placed nowhere: to the core switch, to check.
    assert rows["cam-loose to sw-core"]["chip"] == "Check" and "Nothing records where" in rows["cam-loose to sw-core"]["why"]
    # Each end is the device itself, the one chosen in its select.
    assert rows["srv1 to sw-core"]["a"] == f"device:{d['srv1']['id']}"
    assert rows["srv1 to sw-core"]["b"] == f"device:{d['core']['id']}"
    # Already cabled, wireless, a patch panel, a monitor: left out.
    assert not any(n.startswith(("lp ", "ext1", "pp1", "monitor")) for n in rows)


def test_a_switch_with_its_ports_recorded_gives_its_free_ports(client, h, admin):
    site = make(client, h, "site", name="Home")
    sw = make(client, h, "network_device", name="sw1", location_id=site["id"], **{"f.kind": "switch"})
    post(client, h, f"/network/devices/{sw['id']}/ports", prefix="Port ", first=1, last=2)
    for name in ("a-pc", "b-pc", "c-pc"):
        make(client, h, "workstation", name=name, location_id=site["id"])
    ports = {p["name"]: p["id"] for p in client.get(f"/network/devices/{sw['id']}/ports").get_json()["ports"]}
    _, rows = suggest(client, h, site)
    assert rows["a-pc to sw1"]["b"] == f"port:{ports['Port 1']}" and rows["b-pc to sw1"]["b"] == f"port:{ports['Port 2']}"
    # The third has no port left: to choose, unticked.
    assert rows["c-pc to sw1"]["chip"] == "Choose a port" and not rows["c-pc to sw1"]["checked"]
    assert "sw1 has no free port left" in rows["c-pc to sw1"]["why"]


def test_a_device_plugs_into_a_switch_that_carries_its_network(client, h, admin):
    site = make(client, h, "site", name="Home")
    room = make(client, h, "room", name="Office", location_id=site["id"])
    iot = make(client, h, "subnet", name="IoT", **{"f.cidr": "10.0.40.0/24"})
    make(client, h, "network_device", name="sw-a", location_id=room["id"], **{"f.kind": "switch"})
    make(client, h, "network_device", name="sw-iot", location_id=site["id"],
         **{"f.kind": "switch", "s.networks.list": str(iot["id"])})
    make(client, h, "ip_camera", name="cam1", location_id=room["id"], **{"s.addresses.list": "10.0.40.21"})
    make(client, h, "workstation", name="pc1", location_id=room["id"])
    _, rows = suggest(client, h, site)
    # Nearer sw-a is in the same room, but sw-iot carries the camera's subnet.
    assert rows["cam1 to sw-iot"]["chip"] == "Likely" and "carries its network, IoT" in rows["cam1 to sw-iot"]["why"]
    assert "pc1 to sw-a" in rows


def test_a_switch_cabled_as_a_whole_takes_as_many_as_its_ports(client, h, admin):
    site = make(client, h, "site", name="Home")
    make(client, h, "network_device", name="sw1", location_id=site["id"], **{"f.kind": "switch", "f.ports": 2})
    for name in ("a-pc", "b-pc", "c-pc"):
        make(client, h, "workstation", name=name, location_id=site["id"])
    _, rows = suggest(client, h, site)
    assert [rows[f"{n} to sw1"]["chip"] for n in ("a-pc", "b-pc", "c-pc")] == ["Likely", "Likely", "Choose a port"]
    assert "sw1 has no free port left: choose another end, or give it more ports" in rows["c-pc to sw1"]["why"]


def test_the_cables_checked_are_added(client, h, admin):
    d = lab(client, h)
    _, rows = suggest(client, h, d["site"])
    form = {"count": len(rows), "back": "/site-setup/cables?site=1"}
    for title, r in rows.items():
        i = r["i"]
        form.update({f"use{i}": r["checked"] and title != "desk-pc to sw-office", f"a{i}": r["a"], f"b{i}": r["b"],
                     f"label{i}": "C1" if title == "srv1 to sw-core" else "", f"title{i}": title})
    # One changed to an end that can't be: said why, the rest kept.
    bad = rows["ap-office to sw-office"]["i"]
    form[f"b{bad}"] = form[f"a{bad}"]
    done = post(client, h, "/network/cables/suggest/add", **form)["html"]
    assert "9 cables added, 1 left out, and 1 that couldn't be added" in done
    assert "ap-office to sw-office" in done and 'href="/site-setup/cables?site=1"' in done
    cable = client.get(f"/network/devices/{d['srv1']['id']}/ports").get_json()["ports"][0]["cable"]
    assert cable["to"] == "sw-core" and cable["label"] == "C1"
    # Asked again, only what is still loose is suggested.
    _, rows = suggest(client, h, d["site"])
    assert set(rows) == {"ap-office to sw-office", "desk-pc to sw-office"}


def test_the_button_is_in_the_cables_step(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    page = client.get("/site-setup/cables").data.decode()
    assert 'data-open="cabling-modal"' in page and 'id="cabling-modal"' in page
    # The button works the cables out as it opens the dialog; how, behind its info button.
    assert 'data-api-post="/network/cables/suggest"' in page and 'popovertarget="cabling-how-help"' in page
    empty = post(client, h, "/network/cables/suggest", site=1)["html"]
    assert "Nothing to suggest" in empty


def test_the_ends_to_choose_are_grouped_by_kind(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    make(client, h, "ups", name="ups1")
    make(client, h, "server", name="srv1")
    make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    make(client, h, "network_device", name="modem", **{"f.kind": "modem"})
    core = make(client, h, "network_device", name="sw-core", **{"f.kind": "switch"})
    post(client, h, f"/network/devices/{core['id']}/ports", prefix="Port ", first=1, last=1)
    page = client.get("/site-setup/cables").data.decode().split("data-row-new")[1]
    groups = re.findall(r'<optgroup label="([^"]+)"', page.split('name="to"')[0])
    assert groups == ["Modems", "Switches", "Servers", "UPSes", "sw-core ports"]


def test_the_cables_step_draws_the_network_once_there_are_cables(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    pc = make(client, h, "workstation", name="pc1")
    assert "The network so far" not in client.get("/site-setup/cables").data.decode()
    post(client, h, "/network/cables", device_id=pc["id"], other_device_id=sw["id"])
    page = client.get("/site-setup/cables").data.decode()
    assert "The network so far" in page and 'aria-label="Network diagram"' in page and "data-zoom" in page
    # Drawn again with the rows, as a cable is added or deleted.
    assert 'aria-label="Network diagram"' in client.get("/site-setup/cables/rows").data.decode()


def test_a_cable_in_the_step_can_be_moved_to_another_end(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    post(client, h, f"/network/devices/{sw['id']}/ports", prefix="Port ", first=1, last=2)
    ports = {p["name"]: p["id"] for p in client.get(f"/network/devices/{sw['id']}/ports").get_json()["ports"]}
    pc = make(client, h, "workstation", name="pc1")
    laptop = make(client, h, "workstation", name="laptop")
    post(client, h, "/site-setup/cables/rows",
         values={"from": f"device:{pc['id']}", "to": f"port:{ports['Port 1']}", "label": "C1"})
    cable = client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"][0]["cable"]
    # Its row has both ends to choose, its own among them though taken.
    page = client.get("/site-setup/cables").data.decode()
    row = page.split(f'data-row-id="{cable["id"]}"')[1].split("</fieldset>")[0]
    assert f'<option value="port:{ports["Port 1"]}" selected' in row and f'value="port:{ports["Port 2"]}"' in row
    # Another port at one end, another device at the other: the same cable, its label kept.
    url = f"/site-setup/cables/rows/{cable['id']}"
    post(client, h, url, name="to", value=f"port:{ports['Port 2']}")
    post(client, h, url, name="from", value=f"device:{laptop['id']}")
    moved = client.get(f"/network/devices/{laptop['id']}/ports").get_json()["ports"][0]["cable"]
    assert moved["id"] == cable["id"] and moved["to"] == "sw1 Port 2" and moved["label"] == "C1"
    assert client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"] == []
    # Onto a port that has a cable already: refused, saying so.
    post(client, h, "/network/cables", device_id=pc["id"], to=f"port:{ports['Port 1']}")
    error = post(client, h, url, 400, name="to", value=f"port:{ports['Port 1']}")["error"]
    assert error == "sw1 Port 1 already has a cable, to pc1."


def test_a_cable_row_folds_to_its_label_and_its_ends_in_label_order(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    for name, label in (("pc-a", "20-10"), ("pc-b", "20-2"), ("pc-c", "")):
        pc = make(client, h, "workstation", name=name)
        post(client, h, "/network/cables", device_id=pc["id"], other_device_id=sw["id"], label=label)
    page = client.get("/site-setup/cables").data.decode()
    assert '<code class="slug guide-row-badge" data-row-badge="label">20-2</code>' in page
    assert '<span class="guide-row-title guide-row-title--full" data-row-title>pc-b → sw1</span>' in page
    assert '<code class="slug guide-row-badge is-empty" data-row-badge="label">No label</code>' in page
    assert 'data-in-title="from to label"' in page
    assert page.index("pc-b → sw1") < page.index("pc-a → sw1") < page.index("pc-c → sw1")


def test_a_site_of_several_buildings_is_cabled_a_building_at_a_time(client, h, admin):
    site = make(client, h, "site", name="Campus")
    main = make(client, h, "building", name="Main", location_id=site["id"])
    annex = make(client, h, "building", name="Annex", location_id=site["id"])
    sheds = make(client, h, "building", name="Sheds", location_id=site["id"])

    def gear(name, kind, where):
        return make(client, h, "network_device", name=name, location_id=where["id"], **{"f.kind": kind})
    # No equipment yet, or all of it in one building: no parts, the step as it was.
    assert "guide-units" not in client.get(f"/site-setup/cables?site={site['id']}").data.decode()
    gear("lonely", "switch", main)
    assert "guide-units" not in client.get(f"/site-setup/cables?site={site['id']}").data.decode()
    # Two buildings with their own subnet, each its own gateway, switch and devices; a camera in a shed;
    # a printer in the site itself.
    for b in (main, annex):
        make(client, h, "subnet", name=f"{b['name']} LAN", location_id=b["id"], **{"f.cidr": "192.168.1.0/24"})
    d = {n: gear(n, k, b) for n, k, b in (("fw-main", "router", main), ("sw-main", "switch", main),
                                         ("fw-annex", "router", annex), ("sw-annex", "switch", annex))}
    d["pc-main"] = make(client, h, "workstation", name="pc-main", location_id=main["id"])
    d["pc-annex"] = make(client, h, "workstation", name="pc-annex", location_id=annex["id"])
    d["cam"] = make(client, h, "ip_camera", name="cam-shed", location_id=sheds["id"])
    d["lp"] = make(client, h, "printer", name="lp-yard", location_id=site["id"])
    post(client, h, "/network/cables", device_id=d["pc-main"]["id"], other_device_id=d["sw-main"]["id"])
    post(client, h, "/network/cables", device_id=d["sw-main"]["id"], other_device_id=d["sw-annex"]["id"])
    page = client.get(f"/site-setup/cables?site={site['id']}").data.decode()
    parts = page.split('class="seg seg--links guide-units"')[1].split("</nav>")[0]
    # Every building with equipment in it, then what is in no building.
    assert re.findall(r">([^<]+)</a>", parts) == ["Annex", "Main", "Sheds", "Not in a building", "Whole site"]
    assert 'class="is-active" aria-current="page">Annex<' in parts            # the first, unless chosen
    # A building's cables: those with an end in it, the one between buildings in both; its own ends
    # first, then every other part's under its name, so anything on the site can be cabled from it.
    annex_page = client.get(f"/site-setup/cables?site={site['id']}&unit={annex['id']}").data.decode()
    rows = annex_page.split("data-row-new")[0]
    assert "sw-main → sw-annex" in rows and "pc-main → sw-main" not in rows
    new_row = annex_page.split("data-row-new")[1].split("</fieldset>")[0]
    assert new_row.index(">pc-annex<") < new_row.index('label="Main · Workstations"') < new_row.index(">pc-main<")
    assert '<optgroup label="Sheds · IP cameras">' in new_row and '<optgroup label="Not in a building · Printers">' in new_row
    assert f'data-rows-url="/site-setup/cables/rows?site={site["id"]}&amp;unit={annex["id"]}"' in annex_page
    whole = client.get(f"/site-setup/cables?site={site['id']}&unit=all").data.decode().split("data-row-new")
    assert "pc-main → sw-main" in whole[0] and ">pc-annex<" in whole[1] and ">cam-shed<" in whole[1]
    # Suggested for one building: its own gateway and switch, nothing of the other's.
    html = post(client, h, "/network/cables/suggest", site=site["id"], unit=str(annex["id"]),
                back="/site-setup/cables")["html"]
    assert "fw-annex to sw-annex" in html and "pc-annex to sw-annex" in html
    assert not re.search(r"<span>[^<]*(fw|sw|pc)-main[^<]*</span>", html)     # nothing of Main's suggested
    assert f'"unit": "{annex["id"]}"' in annex_page.replace("&#34;", '"')


def test_the_cables_hang_from_where_the_internet_comes_in(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)

    def gear(name, kind, **more):
        return make(client, h, "network_device", name=name, **{"f.kind": kind, **more})
    modem = gear("modem", "modem", **{"s.internet.line": True})
    fw = make(client, h, "firewall", name="fw")
    core, office = gear("sw-core", "switch"), gear("sw-office", "switch")
    srv, pc = make(client, h, "server", name="srv"), make(client, h, "workstation", name="pc")
    # Made in no order, and cabled either way round.
    for a, b in ((pc, office), (core, office), (srv, core), (fw, modem), (core, fw)):
        post(client, h, "/network/cables", device_id=a["id"], other_device_id=b["id"])
    page = client.get("/site-setup/cables").data.decode().split("data-row-new")[0]
    heads = re.findall(r'<p class="kicker guide-kind"(?: data-depth="(\d)")?>([^<]+)</p>', page)
    assert heads == [("", "modem · Modem, the internet comes in"), ("1", "fw · Firewall"),
                     ("2", "sw-core · Switch"), ("3", "sw-office · Switch"), ("", "Add another")]
    # Under each, its cables: the switch below it before what plugs in beside it.
    core_part = page.split("sw-core · Switch</p>")[1].split('<p class="kicker')[0]
    assert core_part.index("sw-office") < core_part.index("srv")
    assert 'data-depth="3"' in page.split("sw-office · Switch</p>")[1]


def test_two_lines_are_each_a_top_of_the_cables(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    fiber = make(client, h, "network_device", name="fiber", **{"f.kind": "modem", "s.internet.line": True})
    lte = make(client, h, "network_device", name="lte", **{"f.kind": "modem", "s.internet.line": True})
    fw = make(client, h, "firewall", name="fw")
    for m in (fiber, lte):
        post(client, h, "/network/cables", device_id=fw["id"], other_device_id=m["id"])
    page = client.get("/site-setup/cables").data.decode().split("data-row-new")[0]
    heads = re.findall(r'<p class="kicker guide-kind"(?: data-depth="(\d)")?>([^<]+)</p>', page)
    assert heads[:2] == [("", "fiber · Modem, the internet comes in"), ("", "lte · Modem, the internet comes in")]
