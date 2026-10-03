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
