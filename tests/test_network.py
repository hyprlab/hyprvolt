"""The Network module: subnets, VLANs and IP addresses with their checks,
the addresses section and tab on other records, the subnet view, ports and
cables with tracing, DNS records, search, filters and roles."""
from datetime import date, timedelta

from .conftest import make, section


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def error(client, h, type_, **data):
    resp = client.post("/api/entities", json={"type": type_, **data}, headers=h)
    assert resp.status_code == 400, resp.get_json()
    return resp.get_json()["error"]


def history(client, entity_id):
    return client.get(f"/api/entities/{entity_id}/history").get_json()["history"]


# ———— Subnets, VLANs, IP addresses ————

def test_subnets_are_checked_and_normalized(client, h, admin):
    home = make(client, h, "network", name="Home", **{"f.kind": "lan"})
    subnet = make(client, h, "subnet", name="Servers", **{"f.cidr": "10.0.20.7/24", "f.network": home["id"],
                                                          "f.gateway": "10.0.20.1",
                                                          "f.dhcp_range": "10.0.20.100 – 10.0.20.199"})
    assert subnet["fields"]["cidr"] == "10.0.20.0/24"
    assert subnet["fields"]["dhcp_range"] == "10.0.20.100-10.0.20.199"
    assert "subnet with its prefix" in error(client, h, "subnet", name="x", **{"f.cidr": "10.0.20"})
    assert "outside 10.0.21.0/24" in error(client, h, "subnet", name="x",
                                           **{"f.cidr": "10.0.21.0/24", "f.gateway": "10.0.20.1"})
    assert "DHCP range must be inside" in error(client, h, "subnet", name="x",
                                                **{"f.cidr": "10.0.21.0/24", "f.dhcp_range": "10.0.20.1-10.0.20.9"})
    assert "needs its first and its last address" in error(client, h, "subnet", name="x",
                                                **{"f.cidr": "10.0.21.0/24", "f.dhcp_range": "10.0.21.9"})
    assert "already recorded as Servers" in error(client, h, "subnet", name="x",
                                                  **{"f.cidr": "10.0.20.0/24", "f.network": home["id"]})
    # The same range in another network is fine: two sites can both use it.
    office = make(client, h, "network", name="Office")
    make(client, h, "subnet", name="Office servers", **{"f.cidr": "10.0.20.0/24", "f.network": office["id"]})


def test_vlan_ids_are_unique_within_a_network(client, h, admin):
    home = make(client, h, "network", name="Home")
    office = make(client, h, "network", name="Office")
    make(client, h, "vlan", name="Servers", **{"f.vid": 20, "f.network": home["id"]})
    assert "already Servers in this network" in error(client, h, "vlan", name="x",
                                                      **{"f.vid": 20, "f.network": home["id"]})
    make(client, h, "vlan", name="Office servers", **{"f.vid": 20, "f.network": office["id"]})
    assert "between 1 and 4094" in error(client, h, "vlan", name="x", **{"f.vid": 5000})


def test_an_ip_address_is_named_by_its_address(client, h, admin):
    server = make(client, h, "server", name="srv1")
    ip = make(client, h, "ip_address", **{"f.address": "10.0.20.5", "f.assigned": server["id"]})
    assert ip["name"] == "10.0.20.5" and ip["slug"] == "10-0-20-5" and ip["status_label"] == "In use"
    v6 = make(client, h, "ip_address", **{"f.address": "FD00:0::11"})
    assert v6["name"] == "fd00::11"
    assert "already recorded, assigned to srv1" in error(client, h, "ip_address", **{"f.address": "10.0.20.5"})
    assert "must be an IP address" in error(client, h, "ip_address", **{"f.address": "10.0.20.300"})
    assert "Address is required" in error(client, h, "ip_address", **{"f.address": ""})
    # Assigned to anything addressable, from any module; not to a place.
    vm = make(client, h, "vm", name="docker1")
    client.post(f"/api/entities/{ip['id']}", json={"f.assigned": vm["id"]}, headers=h)
    site = make(client, h, "site", name="Home")
    assert "right type" in error(client, h, "ip_address", **{"f.address": "10.0.20.9", "f.assigned": site["id"]})
    # Changing the address renames it.
    got = post(client, h, f"/api/entities/{ip['id']}", **{"f.address": "10.0.20.6"})["entity"]
    assert got["name"] == "10.0.20.6"
    assert {"field": "name", "label": "Name", "old": "10.0.20.5", "new": "10.0.20.6"} in history(client, ip["id"])[0]["changes"]
    form = client.get("/e/form?type=ip_address").data.decode()
    assert 'name="name"' not in form and 'name="f.address"' in form and "Made from the address" in form
    choices = client.get("/e/form?type=ip_address").data.decode()
    assert "docker1 · Virtual machine" in choices and "srv1 · Server" in choices and "Home · Site" not in choices


# ———— The addresses section and tab ————

def test_a_device_lists_its_addresses_in_its_form(client, h, admin):
    make(client, h, "subnet", name="Servers", **{"f.cidr": "10.0.20.0/24"})
    server = make(client, h, "server", name="srv1", **{"s.addresses.list": "10.0.20.5, 10.0.20.6 ; 10.0.20.5"})
    ips = client.get("/api/entities?type=ip_address").get_json()["entities"]
    assert sorted(e["name"] for e in ips) == ["10.0.20.5", "10.0.20.6"]
    created = history(client, server["id"])[-1]
    assert {"field": "addresses", "label": "IP addresses", "old": "", "new": "10.0.20.5, 10.0.20.6"} in created["changes"]
    form = client.get(f"/e/{server['id']}/form").data.decode()
    assert 'name="s.addresses.list" value="10.0.20.5, 10.0.20.6"' in form
    tab = client.get(f"/e/{server['id']}/sheet?tab=addresses").data.decode()
    assert "10.0.20.5" in tab and "Servers (10.0.20.0/24)" in tab
    # Taking one off deletes it; one with notes is only unassigned.
    six = next(e for e in ips if e["name"] == "10.0.20.6")
    client.post(f"/api/entities/{six['id']}", json={"notes": "Keep for the VIP."}, headers=h)
    client.post(f"/api/entities/{server['id']}", json={"s.addresses.list": "10.0.20.7"}, headers=h)
    live = {e["name"]: e for e in client.get("/api/entities?type=ip_address").get_json()["entities"]}
    assert set(live) == {"10.0.20.6", "10.0.20.7"}
    assert client.get(f"/api/entities/{six['id']}").get_json()["entity"]["fields"]["assigned"] is None
    # An address another device holds is refused, and nothing is saved.
    other = make(client, h, "server", name="srv2")
    resp = client.post(f"/api/entities/{other['id']}", json={"name": "renamed", "s.addresses.list": "10.0.20.7"},
                       headers=h)
    assert resp.status_code == 400 and "assigned to srv1" in resp.get_json()["error"]
    assert client.get(f"/api/entities/{other['id']}").get_json()["entity"]["name"] == "srv2"
    assert "not an IP address" in error(client, h, "server", name="x", **{"s.addresses.list": "10.0.20"})
    # Places and documents get no such section.
    assert "s.addresses" not in client.get("/e/form?type=site").data.decode()


# ———— The subnet view ————

def test_the_subnet_view_shows_what_is_used_reserved_and_free(client, h, admin, viewer):
    subnet = make(client, h, "subnet", name="Clients", **{"f.cidr": "10.0.30.0/28", "f.gateway": "10.0.30.1",
                                                          "f.dhcp_range": "10.0.30.8-10.0.30.11"})
    pc = make(client, h, "workstation", name="desk-pc", **{"s.addresses.list": "10.0.30.5"})
    make(client, h, "ip_address", status="reserved", **{"f.address": "10.0.30.6"})
    make(client, h, "ip_address", **{"f.address": "10.0.40.6"})                  # elsewhere
    got = client.get(f"/network/subnets/{subnet['id']}/addresses").get_json()
    assert got["subnet"] == {"id": subnet["id"], "name": "Clients", "cidr": "10.0.30.0/28", "hosts": 14,
                             "used": 3, "dhcp": 4, "free": 7}
    assert [(a["address"], a["state"], (a["assigned"] or {}).get("name")) for a in got["addresses"]] == [
        ("10.0.30.5", "used", "desk-pc"), ("10.0.30.6", "reserved", None)]
    tab = client.get(f"/e/{subnet['id']}/sheet?tab=addresses").data.decode()
    assert f'class="ipcell is-used" href="/e/{pc["id"]}" data-entity="{pc["id"]}" title="10.0.30.5 · desk-pc"' in tab
    assert 'class="ipcell is-gateway"' in tab and 'class="ipcell is-reserved"' in tab
    assert '<span role="listitem" class="ipcell is-dhcp"' in tab
    assert """data-new-fields='{"address": "10.0.30.2"}'""" in tab
    other, _ = viewer
    assert "data-new-fields" not in other.get(f"/e/{subnet['id']}/sheet?tab=addresses").data.decode()
    ip = client.get("/api/entities?type=ip_address&q=10.0.30.5").get_json()["entities"][0]
    assert "Clients" in client.get(f"/e/{ip['id']}/sheet?tab=network").data.decode()
    assert "Subnets" in client.get("/").data.decode()


# ———— Ports and cables ————

def rack(client, h):
    switch = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    panel = make(client, h, "network_device", name="pp1", **{"f.kind": "patch_panel"})
    pc = make(client, h, "workstation", name="pc")
    post(client, h, f"/network/devices/{switch['id']}/ports", prefix="Port ", first=1, last=4, speed_mbps=1000)
    post(client, h, f"/network/devices/{panel['id']}/ports", first=1, last=2, rear=True)
    post(client, h, f"/network/devices/{pc['id']}/ports", prefix="eth", first=0, last=0)
    ports = {}
    for dev in (switch, panel, pc):
        for p in client.get(f"/network/devices/{dev['id']}/ports").get_json()["ports"]:
            ports[f"{dev['name']} {p['name']}"] = p
    return switch, panel, pc, ports


def test_ports_are_added_named_and_paired(client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    assert [n for n in ports if n.startswith("sw1")] == ["sw1 Port 1", "sw1 Port 2", "sw1 Port 3", "sw1 Port 4"]
    assert ports["pp1 Front 1"]["pair_id"] == ports["pp1 Rear 1"]["id"]
    assert ports["pc eth0"]["speed_mbps"] is None
    again = post(client, h, f"/network/devices/{switch['id']}/ports", 400, first=4, last=5)
    assert "already has a port called Port 4" in again["error"]
    assert "at most 128" in post(client, h, f"/network/devices/{switch['id']}/ports", 400, first=1, last=200)["error"]
    site = make(client, h, "site", name="Home")
    assert client.post(f"/network/devices/{site['id']}/ports", json={}, headers=h).status_code == 404
    assert history(client, switch["id"])[0]["changes"][0]["new"] == "Port 1 to Port 4 (4)"


def test_a_cable_path_is_traced_through_a_patch_panel(client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    post(client, h, "/network/cables", port_id=ports["pc eth0"]["id"], other_id=ports["pp1 Rear 1"]["id"],
         label="Office jack 1", length_m=18)
    made = post(client, h, "/network/cables", port_id=ports["pp1 Front 1"]["id"], other_id=ports["sw1 Port 3"]["id"])
    assert made["cable"]["trace"] == "pp1 Front 1 → sw1 Port 3"
    path = client.get(f"/network/ports/{ports['pc eth0']['id']}/trace").get_json()["path"]
    hops = [s["port"]["device"] + " " + s["port"]["name"] if "port" in s else ("~" if "cable" in s else "=")
            for s in path]
    assert hops == ["pc eth0", "~", "pp1 Rear 1", "=", "pp1 Front 1", "~", "sw1 Port 3"]
    tab = client.get(f"/e/{pc['id']}/sheet?tab=ports").data.decode()
    assert "Trace to the far end" in tab and "sw1</a> Port 3" in tab and "cable Office jack 1, 18 m" in tab
    # One cable per port, and not front to rear of the same pair.
    busy = post(client, h, "/network/cables", 400, port_id=ports["sw1 Port 3"]["id"], other_id=ports["sw1 Port 4"]["id"])
    assert "sw1 Port 3 already has a cable, to pp1 Front 1" in busy["error"]
    loop = post(client, h, "/network/cables", 400, port_id=ports["pp1 Front 2"]["id"], other_id=ports["pp1 Rear 2"]["id"])
    assert "front and rear of the same" in loop["error"]
    assert history(client, pc["id"])[0]["action"] == "cabled"


def test_cables_and_ports_come_back_with_undo(client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    cable = post(client, h, "/network/cables", port_id=ports["pc eth0"]["id"], other_id=ports["sw1 Port 1"]["id"],
                 label="C1")["cable"]
    undo = post(client, h, f"/network/cables/{cable['id']}/delete")["undo"]
    assert client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"][0]["cable"] is None
    post(client, h, undo["url"], **undo["body"])
    assert client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"][0]["cable"]["label"] == "C1"
    # Removing a port takes its cable; Undo puts back both, and a pair.
    undo = post(client, h, f"/network/ports/{ports['pc eth0']['id']}/delete")["undo"]
    assert client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"] == []
    post(client, h, undo["url"], **undo["body"])
    back = client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"][0]
    assert back["id"] == ports["pc eth0"]["id"] and back["cable"]["to"] == "sw1 Port 1"
    undo = post(client, h, f"/network/ports/{ports['pp1 Rear 2']['id']}/delete")["undo"]
    post(client, h, undo["url"], **undo["body"])
    front = next(p for p in client.get(f"/network/devices/{panel['id']}/ports").get_json()["ports"]
                 if p["name"] == "Front 2")
    assert front["pair_id"] == ports["pp1 Rear 2"]["id"]


def test_a_port_is_changed_from_the_sheet(client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    vlan = make(client, h, "vlan", name="Servers", **{"f.vid": 20})
    post(client, h, "/network/ports/edit", port_id=ports["sw1 Port 1"]["id"], name="Uplink", vlan_id=vlan["id"],
         tagged="30, 40", poe=True, mac="AA:BB:CC:00:11:22", speed_mbps="10000")
    got = client.get(f"/network/devices/{switch['id']}/ports").get_json()["ports"][0]
    assert (got["name"], got["vlan_id"], got["tagged"], got["poe"], got["mac"], got["speed_mbps"]) == \
        ("Uplink", vlan["id"], "30, 40", True, "aa:bb:cc:00:11:22", 10000)
    changes = {c["label"]: c["new"] for c in history(client, switch["id"])[0]["changes"]}
    assert changes["Port 1: name"] == "Uplink" and changes["Port 1: VLAN"] == "Servers"
    clash = post(client, h, "/network/ports/edit", 400, port_id=ports["sw1 Port 2"]["id"], name="uplink")
    assert "already has a port called uplink" in clash["error"]
    assert "sw1" in client.get(f"/e/{vlan['id']}/sheet?tab=subnets").data.decode()
    # The palette finds a port by its MAC address.
    found = client.get("/search?q=aa:bb:cc:00").get_json()["groups"]
    assert any(i["title"] == "aa:bb:cc:00:11:22" and i["id"] == switch["id"] for g in found for i in g["items"])


def test_a_device_is_cabled_as_a_whole_until_its_ports_are_recorded(client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    desk = make(client, h, "workstation", name="desk")
    printer = make(client, h, "printer", name="lp")
    tab = client.get(f"/e/{desk['id']}/sheet?tab=ports").data.decode()
    assert "Connect a cable" in tab and "Add ports" not in tab
    assert f'value="device:{printer["id"]}"' in tab and f'value="port:{ports["sw1 Port 2"]["id"]}"' in tab
    assert f'value="device:{switch["id"]}"' not in tab
    # To a switch's port, and to another device as a whole.
    post(client, h, "/network/cables", device_id=desk["id"], to=f"port:{ports['sw1 Port 2']['id']}", label="C2")
    post(client, h, "/network/cables", device_id=desk["id"], other_device_id=printer["id"])
    ends = client.get(f"/network/devices/{desk['id']}/ports").get_json()["ports"]
    assert [(p["name"], p["cable"]["to"]) for p in ends] == [("", "sw1 Port 2"), ("", "lp")]
    tab = client.get(f"/e/{desk['id']}/sheet?tab=ports").data.decode()
    assert "2 cables." in tab and "sw1</a> Port 2" in tab
    assert "has its ports recorded" in post(client, h, "/network/cables", 400, device_id=desk["id"],
                                            other_device_id=switch["id"])["error"]
    assert "another device" in post(client, h, "/network/cables", 400, device_id=desk["id"],
                                    other_device_id=desk["id"])["error"]
    # A cable's ends with no name go with it, and come back with Undo.
    undo = post(client, h, f"/network/cables/{ends[1]['cable']['id']}/delete")["undo"]
    assert len(client.get(f"/network/devices/{printer['id']}/ports").get_json()["ports"]) == 0
    post(client, h, undo["url"], **undo["body"])
    assert client.get(f"/network/devices/{printer['id']}/ports").get_json()["ports"][0]["cable"]["to"] == "desk"
    # Its switch records its ports and shows the ends to be named; off again
    # hides a free port.
    assert 'data-autosubmit aria-label="Record each port"' in tab
    assert post(client, h, f"/network/devices/{desk['id']}/ports/recorded", on=True)["recorded"] is True
    assert history(client, desk["id"])[0]["changes"][0]["label"] == "Record each port"
    tab = client.get(f"/e/{desk['id']}/sheet?tab=ports").data.decode()
    assert "No port named" in tab and "Add ports" in tab and 'data-autosubmit checked' in tab
    post(client, h, "/network/ports/edit", port_id=ends[0]["id"], name="eth0")
    post(client, h, f"/network/devices/{desk['id']}/ports", prefix="wlan", first=0, last=0)
    post(client, h, f"/network/devices/{desk['id']}/ports/recorded", on=False)
    tab = client.get(f"/e/{desk['id']}/sheet?tab=ports").data.decode().split('id="section-ports"')[1]
    tab = tab.split("</section>")[0]
    assert "eth0" in tab and "wlan0" not in tab
    assert len(client.get(f"/network/devices/{desk['id']}/ports").get_json()["ports"]) == 3


def test_devices_with_ports_record_them_after_an_upgrade(app, client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    desk = make(client, h, "workstation", name="desk")
    from hyprvolt.migrate import Migrator
    from hyprvolt.models import db
    from hyprvolt.modules.network import _ports_recorded
    from hyprvolt.modules.network.models import PortsRecorded
    with app.app_context():
        PortsRecorded.query.delete()
        db.session.execute(db.text("DELETE FROM settings WHERE key = 'migration:network:ports-recorded'"))
        db.session.commit()
        _ports_recorded(Migrator("network"))
        got = {r.device_id for r in PortsRecorded.query}
    assert got == {switch["id"], panel["id"], pc["id"]}


def test_viewers_see_ports_but_cannot_change_them(client, h, admin, viewer):
    switch, panel, pc, ports = rack(client, h)
    other, oh = viewer
    assert other.get(f"/network/devices/{switch['id']}/ports").status_code == 200
    assert other.get(f"/network/ports/{ports['sw1 Port 1']['id']}/trace").status_code == 200
    for url, body in ((f"/network/devices/{switch['id']}/ports", {}), ("/network/cables", {}),
                      (f"/network/devices/{switch['id']}/ports/recorded", {"on": False}),
                      (f"/network/ports/{ports['sw1 Port 1']['id']}/delete", {}), ("/network/ports/edit", {})):
        assert other.post(url, json=body, headers=oh).status_code == 403, url
    tab = other.get(f"/e/{switch['id']}/sheet?tab=ports").data.decode().split('id="section-ports"')[1]
    tab = tab.split("</section>")[0]
    assert "Add ports" not in tab and "data-api-post" not in tab and "Record each port" not in tab


# ———— Domains and DNS ————

def test_dns_records_are_checked_and_point_at_devices(client, h, admin):
    domain = make(client, h, "domain", name="Lab.Home.")
    assert domain["name"] == "lab.home"
    assert "the domain itself" in error(client, h, "domain", name="not a domain")
    vm = make(client, h, "vm", name="docker1", **{"s.addresses.list": "10.0.20.11"})
    url = f"/network/domains/{domain['id']}/records"
    post(client, h, url, name="docker1.lab.home", type="A", value="10.0.20.11")
    post(client, h, url, name="grafana", type="CNAME", value="docker1.lab.home.")
    assert "IPv4" in post(client, h, url, 400, name="x", type="A", value="fd00::1")["error"]
    assert "IP address" in post(client, h, url, 400, name="x", type="A", value="docker1")["error"]
    assert "needs a priority" in post(client, h, url, 400, name="@", type="MX", value="mx.example.net")["error"]
    assert "part before it" in post(client, h, url, 400, name="bad name", type="TXT", value="x")["error"]
    rows = client.get(url).get_json()["records"]
    assert [(r["fqdn"], r["type"]) for r in rows] == [("docker1.lab.home", "A"), ("grafana.lab.home", "CNAME")]
    tab = client.get(f"/e/{domain['id']}/sheet?tab=records").data.decode()
    assert tab.count(f'data-entity="{vm["id"]}"') == 2
    addresses = client.get(f"/e/{vm['id']}/sheet?tab=addresses").data.decode()
    assert "docker1.lab.home" in addresses
    undo = post(client, h, f"/network/records/{rows[1]['id']}/delete")["undo"]
    post(client, h, undo["url"], **undo["body"])
    assert len(client.get(url).get_json()["records"]) == 2
    found = client.get("/search?q=grafana").get_json()["groups"]
    assert any(i["title"] == "grafana.lab.home" and i["id"] == domain["id"] for g in found for i in g["items"])


def test_filters_for_loose_addresses_and_renewals(client, h, admin):
    make(client, h, "ip_address", **{"f.address": "10.0.0.9"})
    make(client, h, "ip_address", status="reserved", **{"f.address": "10.0.0.10"})
    make(client, h, "server", name="srv1", **{"s.addresses.list": "10.0.0.11"})
    loose = client.get("/network?f=unassigned&view=list").data.decode()
    assert ">10.0.0.9<" in loose and ">10.0.0.10<" not in loose and ">10.0.0.11<" not in loose
    soon = (date.today() + timedelta(days=20)).isoformat()
    make(client, h, "domain", name="example.net", **{"f.expires": soon})
    make(client, h, "domain", name="example.org", **{"f.expires": (date.today() + timedelta(days=300)).isoformat()})
    due = client.get("/network?f=renewal&view=list").data.decode()
    assert ">example.net<" in due and ">example.org<" not in due


def test_internet_connections_have_a_circuit_and_a_filter(client, h, admin):
    wan = make(client, h, "network", name="Fiber", **{"f.kind": "wan", "f.circuit_id": "SC-88213"})
    make(client, h, "network", name="Home LAN", **{"f.kind": "lan"})
    assert wan["fields"]["circuit_id"] == "SC-88213"
    listed = client.get("/network?f=internet&view=list").data.decode()
    assert ">Fiber<" in listed and ">Home LAN<" not in listed
    # A view, not something to see to: its count isn't red.
    entry = listed.split("Internet connections</span>")[1].split("</a>")[0]
    assert ">1<" in entry and "count--alert" not in entry
    # The ISP is a vendor, chosen in the Supplier section, not a line of text.
    form = client.get(f"/e/form?type=network&id={wan['id']}").data.decode()
    assert "s.supplier.vendor_id" in form and 'name="f.provider"' not in form


def test_a_typed_provider_moves_to_the_notes(app, client, h, admin):
    from hyprvolt.migrate import Migrator
    from hyprvolt.models import db
    from hyprvolt.modules.network import _provider_to_notes
    wan = make(client, h, "network", name="Internet", notes="Bridge mode.", **{"f.kind": "wan"})
    bare = make(client, h, "network", name="Backup line", **{"f.kind": "wan"})
    with app.app_context():
        db.session.execute(db.text("ALTER TABLE network_details ADD COLUMN provider VARCHAR(120)"))
        db.session.execute(db.text("UPDATE network_details SET provider = 'Springfield Cable' WHERE entity_id = :i"),
                           {"i": wan["id"]})
        db.session.execute(db.text("UPDATE network_details SET provider = 'LTE Co' WHERE entity_id = :i"),
                           {"i": bare["id"]})
        db.session.commit()
        for _ in range(2):
            _provider_to_notes(Migrator("network"))
    with app.app_context():
        from hyprvolt.core.models import Entity
        notes = {e.name: e.notes for e in Entity.query.filter_by(type="network")}
    assert notes == {"Internet": "Bridge mode.\n\nProvider: Springfield Cable", "Backup line": "Provider: LTE Co"}


def test_a_subnet_is_typed_as_address_and_mask_and_its_dhcp_as_first_and_last(client, h, admin):
    subnet = make(client, h, "subnet", name="Clients", **{"f.cidr": "10.0.30.0/24",
                                                         "f.dhcp_range": "10.0.30.100 to 10.0.30.199"})
    assert subnet["fields"]["dhcp_range"] == "10.0.30.100-10.0.30.199"
    sheet = client.get(f"/e/{subnet['id']}/sheet").data.decode()
    # The range: its address, and the mask chosen from the sizes beside it.
    assert 'data-join="/" data-prefills="f.gateway f.dhcp_range"' in sheet and 'value="10.0.30.0"' in sheet
    assert '<option value="24" selected>/24 · 255.255.255.0 · 254 hosts</option>' in sheet
    # The DHCP range: its first and last address in two boxes.
    assert 'data-join="-"' in sheet and 'value="10.0.30.100"' in sheet and 'value="10.0.30.199"' in sheet
    wrong = client.post(f"/api/entities/{subnet['id']}", json={"f.dhcp_range": "10.0.30.199-10.0.30.100"}, headers=h)
    assert wrong.status_code == 400 and "first address must come before its last" in wrong.get_json()["error"]
    # A smaller mask would leave the DHCP range outside: refused. A larger one fits.
    small = client.post(f"/api/entities/{subnet['id']}", json={"f.cidr": "10.0.30.0/25"}, headers=h)
    assert small.status_code == 400 and "DHCP range must be inside 10.0.30.0/25" in small.get_json()["error"]
    client.post(f"/api/entities/{subnet['id']}", json={"f.cidr": "10.0.30.0/23"}, headers=h)
    assert client.get(f"/api/entities/{subnet['id']}").get_json()["entity"]["fields"]["cidr"] == "10.0.30.0/23"


def test_an_internet_connection_has_a_download_and_upload_speed(client, h, admin):
    wan = make(client, h, "network", name="Fiber", **{"f.kind": "wan", "f.download": "1 Gb/s", "f.upload": "40 Mbps"})
    assert (wan["fields"]["download"], wan["fields"]["upload"]) == (1000, 40)
    sheet = client.get(f"/e/{wan['id']}/sheet").data.decode()
    assert "1 Gb/s" in sheet and "40 Mb/s" in sheet
    # The control: the number and its unit, the megabits in the saved input.
    assert 'name="f.download" value="1000"' in sheet and '<option value="g" selected>Gb/s</option>' in sheet
    for raw, mbps in (("2.5 Gb/s", 2500), ("1,500 Mb/s", 1500), ("940", 940), (300, 300)):
        client.post(f"/api/entities/{wan['id']}", json={"f.download": raw}, headers=h)
        assert client.get(f"/api/entities/{wan['id']}").get_json()["entity"]["fields"]["download"] == mbps, raw
    bad = client.post(f"/api/entities/{wan['id']}", json={"f.upload": "fast"}, headers=h)
    assert bad.status_code == 400 and "940 Mb/s or 1 Gb/s" in bad.get_json()["error"]


def test_a_static_line_has_its_address_mask_gateway_and_dns(client, h, admin, viewer):
    wan = make(client, h, "network", name="Fiber", **{"f.kind": "wan", "f.static_ip": True,
                                                        "f.public_ips": "203.0.113.26", "f.netmask": "/29",
                                                        "f.gateway": "203.0.113.25", "f.dns_servers": "203.0.113.53"})
    assert wan["fields"]["netmask"] == "255.255.255.248"
    bad = client.post(f"/api/entities/{wan['id']}", json={"f.gateway": "203.0.113.1"}, headers=h)
    assert bad.status_code == 400 and "outside 203.0.113.24/29" in bad.get_json()["error"]
    assert "255.255.255.248, or /29" in client.post(f"/api/entities/{wan['id']}", json={"f.netmask": "255.0.255.0"},
                                                    headers=h).get_json()["error"]
    # The editor's switch, and the static fields that follow it.
    sheet = client.get(f"/e/{wan['id']}/sheet").data.decode()
    assert '<span class="seg seg--choice" role="radiogroup" aria-label="IP address">' in sheet
    assert 'name="f.static_ip" value="1" checked' in sheet and "<span>Dynamic</span>" in sheet
    assert 'data-when="f.static_ip" data-when-is="1">' in sheet          # shown: the line is static
    # Dynamic: a viewer sees Dynamic and none of the static fields.
    client.post(f"/api/entities/{wan['id']}", json={"f.static_ip": False}, headers=h)
    other, _ = viewer
    seen = section(other.get(f"/e/{wan['id']}/sheet").data.decode(), "overview")
    assert "Dynamic" in seen and "Subnet mask" not in seen and "203.0.113.26" not in seen
    assert 'data-when="f.static_ip" data-when-is="1" hidden' in client.get(f"/e/{wan['id']}/sheet").data.decode()
    # A local network has none of an internet connection's fields.
    lan = make(client, h, "network", name="Home LAN", **{"f.kind": "lan"})
    seen = section(other.get(f"/e/{lan['id']}/sheet").data.decode(), "overview")
    assert "Download" not in seen and "Circuit ID" not in seen and "IP address" not in seen


def test_a_line_comes_in_at_its_modem_router_or_firewall(client, h, admin):
    fiber = make(client, h, "network", name="Fiber", **{"f.kind": "wan"})
    lte = make(client, h, "network", name="LTE", **{"f.kind": "wan"})
    make(client, h, "network", name="Home LAN", **{"f.kind": "lan"})
    modem = make(client, h, "network_device", name="Modem", **{"f.kind": "modem"})
    # From the device: its Internet connection section, offering only lines.
    form = client.get(f"/e/{modem['id']}/form").data.decode()
    assert 'name="s.internet.line"' in form and ">Fiber<" in form and ">Home LAN<" not in form
    client.post(f"/api/entities/{modem['id']}", json={"s.internet.line": fiber["id"]}, headers=h)
    got = client.get(f"/api/entities/{fiber['id']}").get_json()["entity"]["fields"]
    assert got["comes_in_at"] == modem["id"]
    rels = client.get(f"/api/entities/{modem['id']}/relationships").get_json()["relationships"]
    assert any(r["other"]["id"] == fiber["id"] and r["label"] == "brings in" for r in rels)
    # Another line chosen: the first no longer comes in there.
    client.post(f"/api/entities/{modem['id']}", json={"s.internet.line": lte["id"]}, headers=h)
    assert client.get(f"/api/entities/{fiber['id']}").get_json()["entity"]["fields"]["comes_in_at"] is None
    assert client.get(f"/api/entities/{lte['id']}").get_json()["entity"]["fields"]["comes_in_at"] == modem["id"]
    client.post(f"/api/entities/{modem['id']}", json={"s.internet.line": ""}, headers=h)
    assert client.get(f"/api/entities/{lte['id']}").get_json()["entity"]["fields"]["comes_in_at"] is None
    # A switch is network gear too, but a workstation has no such section.
    pc = make(client, h, "workstation", name="pc")
    assert "s.internet" not in client.get(f"/e/{pc['id']}/form").data.decode()
    bad = client.post(f"/api/entities/{modem['id']}", json={"s.internet.line": pc["id"]}, headers=h)
    assert bad.status_code == 400 and "internet connection that exists" in bad.get_json()["error"]


def test_a_line_with_addresses_becomes_static(app, client, h, admin):
    from hyprvolt.migrate import Migrator
    from hyprvolt.models import db
    from hyprvolt.modules.network import _static_ip
    old = make(client, h, "network", name="Old line", **{"f.kind": "wan", "f.public_ips": "198.51.100.7"})
    bare = make(client, h, "network", name="Bare", **{"f.kind": "wan"})
    with app.app_context():
        db.session.execute(db.text("UPDATE network_details SET static_ip = NULL"))
        db.session.execute(db.text("DELETE FROM settings WHERE key = 'migration:network:static-ip'"))
        db.session.commit()
        _static_ip(Migrator("network"))
    get = lambda e: client.get(f"/api/entities/{e['id']}").get_json()["entity"]["fields"]["static_ip"]
    assert get(old) is True and not get(bare)


def test_bandwidth_text_becomes_speeds_or_notes(app, client, h, admin):
    from hyprvolt.migrate import Migrator
    from hyprvolt.models import db
    from hyprvolt.modules.network import _bandwidth_speeds
    lines = {"Fiber": "1 Gb/s down, 40 Mb/s up", "Cable": "940/40 Mbps", "LTE": "fast when it works",
             "Office": "500 Mb/s fiber, static IP"}
    made = {n: make(client, h, "network", name=n, **{"f.kind": "wan"}) for n in lines}
    with app.app_context():
        for n, text in lines.items():
            db.session.execute(db.text("UPDATE network_details SET bandwidth = :t WHERE entity_id = :i"),
                               {"t": text, "i": made[n]["id"]})
        # As on an install from before: the step not yet run.
        db.session.execute(db.text("DELETE FROM settings WHERE key = 'migration:network:bandwidth-speeds'"))
        db.session.commit()
        for _ in range(2):
            _bandwidth_speeds(Migrator("network"))
    got = {n: client.get(f"/api/entities/{made[n]['id']}").get_json()["entity"] for n in lines}
    speeds = {n: (e["fields"]["download"], e["fields"]["upload"]) for n, e in got.items()}
    assert speeds == {"Fiber": (1000, 40), "Cable": (940, 40), "LTE": (None, None), "Office": (500, None)}
    with app.app_context():
        from hyprvolt.core.models import Entity
        notes = {e.name: e.notes for e in Entity.query.filter_by(type="network")}
    assert notes == {"Fiber": "", "Cable": "", "LTE": "Bandwidth: fast when it works",
                     "Office": "Bandwidth: 500 Mb/s fiber, static IP"}


def test_network_off_hides_its_parts_on_other_records(client, h, admin):
    server = make(client, h, "server", name="srv1")
    client.post("/admin/modules/network", json={"enabled": False}, headers=h)
    assert "s.addresses" not in client.get("/e/form?type=server").data.decode()
    sheet = client.get(f"/e/{server['id']}/sheet").data.decode()
    assert "Cabling" not in sheet.split('class="tabs"')[1].split("</nav>")[0]
    assert client.get(f"/network/devices/{server['id']}/ports").status_code == 404


def test_the_demo_network(client, h, admin):
    client.post("/admin/seed-demo", headers=h)
    pc = client.get("/api/entities?type=workstation").get_json()["entities"][0]
    eth0 = client.get(f"/network/devices/{pc['id']}/ports").get_json()["ports"][0]
    path = client.get(f"/network/ports/{eth0['id']}/trace").get_json()["path"]
    assert path[-1]["port"]["device"] == "sw-core" and path[-1]["port"]["name"] == "Port 5"
    servers = client.get("/api/entities?type=subnet&q=10.0.20.0").get_json()["entities"][0]
    got = client.get(f"/network/subnets/{servers['id']}/addresses").get_json()
    assert {"10.0.20.5", "10.0.20.11", "10.0.20.250"} <= {a["address"] for a in got["addresses"]}


# ———— Wireless networks ————

def test_wireless_networks_are_broadcast_by_wireless_gear(client, h, admin):
    vlan = make(client, h, "vlan", name="IoT", **{"f.vid": 30})
    home = make(client, h, "wifi", name="home", **{"f.security": "wpa2_wpa3", "f.bands": "2.4_5"})
    iot = make(client, h, "wifi", name="iot", **{"f.security": "wpa2", "f.hidden_ssid": True, "f.vlan": vlan["id"]})
    assert iot["fields"]["vlan"] == vlan["id"] and iot["fields"]["hidden_ssid"] is True
    ap = make(client, h, "access_point", name="ap-hall")
    ext = make(client, h, "network_device", name="ext-garage", **{"f.kind": "extender"})
    switch = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    # Ticked on the access point, read the same from the network.
    client.post(f"/api/entities/{ap['id']}", json={"s.wifi.list": f"{home['id']},{iot['id']}"}, headers=h)
    rels = client.get(f"/api/entities/{home['id']}/relationships").get_json()["relationships"]
    assert [r["other"]["name"] for r in rels if r["label"] == "is broadcast by"] == ["ap-hall"]
    assert any(c["label"] == "Wireless networks" and c["new"] == "home, iot"
               for e in history(client, ap["id"]) for c in e["changes"])
    # Ticked on the network: the extender added, the access point kept.
    client.post(f"/api/entities/{home['id']}", json={"s.broadcast.list": f"{ap['id']},{ext['id']}"}, headers=h)
    form = client.get(f"/e/{home['id']}/form").data.decode()
    assert f'value="{ap["id"]},{ext["id"]}"' in form and ">sw1<" not in form
    # Unticked on the access point: iot is no longer broadcast by it.
    client.post(f"/api/entities/{ap['id']}", json={"s.wifi.list": str(home["id"])}, headers=h)
    assert not [r for r in client.get(f"/api/entities/{iot['id']}/relationships").get_json()["relationships"]
                if r["label"] == "is broadcast by"]
    # Only wireless gear broadcasts: a switch is refused, and its form hides the section.
    bad = client.post(f"/api/entities/{home['id']}", json={"s.broadcast.list": str(switch["id"])}, headers=h)
    assert bad.status_code == 400 and "wireless gear that exists" in bad.get_json()["error"]
    switch_form = client.get(f"/e/{switch['id']}/form").data.decode()
    assert '<div data-section="wifi" hidden>' in switch_form and '<div data-section="bridge" hidden>' in switch_form
    ext_form = client.get(f"/e/{ext['id']}/form").data.decode()
    assert '<div data-section="wifi">' in ext_form and '<div data-section="bridge" hidden>' in ext_form
    assert "wifi=switch,patch_panel,moca,other," in ext_form


def test_a_hypervisor_takes_the_address_of_the_server_it_runs_on(client, h, admin):
    srv = make(client, h, "server", name="srv1", **{"s.addresses.list": "10.0.20.21"})
    other = make(client, h, "server", name="srv2", **{"s.addresses.list": "10.0.20.22"})
    resp = client.post("/api/entities", json={"type": "hypervisor", "name": "pve1", "f.host": srv["id"],
                                              "s.addresses.list": "10.0.20.21"}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["notices"] == ["10.0.20.21 moved from the server srv1 to the hypervisor pve1 running on it."]
    ip = client.get("/api/entities?type=ip_address&q=10.0.20.21").get_json()["entities"][0]
    assert client.get(f"/api/entities/{ip['id']}").get_json()["entity"]["fields"]["assigned"] == resp.get_json()["entity"]["id"]
    assert any(c["label"] == "IP addresses" and c["new"] == "moved to pve1"
               for e in history(client, srv["id"]) for c in e["changes"])
    # Another server's address, or a VM given its host's, is still refused.
    assert "assigned to srv2" in error(client, h, "hypervisor", name="pve2", **{"f.host": srv["id"],
                                                                                "s.addresses.list": "10.0.20.22"})
    pve = resp.get_json()["entity"]
    assert "assigned to pve1" in error(client, h, "vm", name="vm1", **{"f.host": pve["id"],
                                                                       "s.addresses.list": "10.0.20.21"})


def test_switches_routers_and_firewalls_carry_vlans_and_subnets(client, h, admin):
    vlan = make(client, h, "vlan", name="IoT", **{"f.vid": 40})
    make(client, h, "subnet", name="IoT", **{"f.cidr": "10.0.40.0/24", "f.vlan": vlan["id"]})
    lab = make(client, h, "subnet", name="Lab", **{"f.cidr": "10.0.50.0/24"})
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch",
                                                           "s.networks.list": f"{vlan['id']},{lab['id']}"})
    fw = make(client, h, "firewall", name="fw1")
    form = client.get(f"/e/{sw['id']}/form").data.decode()
    # The VLANs by number, the subnets by range, each saying its VLAN.
    assert "IoT (VLAN 40)" in form and "IoT, 10.0.40.0/24, on VLAN 40" in form and "Lab, 10.0.50.0/24" in form
    assert f'value="{vlan["id"]}" data-multi-item checked' in form
    # The other way round, from the subnet: the firewall too.
    post(client, h, f"/api/entities/{lab['id']}", **{"s.carriers.list": f"{sw['id']},{fw['id']}"})
    rels = client.get(f"/api/entities/{fw['id']}/relationships").get_json()["relationships"]
    assert [(r["label"], r["other"]["name"]) for r in rels] == [("carries", "Lab")]
    # An access point, or a patch panel, carries nothing: refused, and hidden by its kind.
    ap = make(client, h, "access_point", name="ap1")
    assert "a switch, router or firewall" in post(client, h, f"/api/entities/{lab['id']}", 400,
                                                  **{"s.carriers.list": str(ap["id"])})["error"]
    panel = make(client, h, "network_device", name="pp1", **{"f.kind": "patch_panel"})
    assert '<div data-section="networks" hidden>' in client.get(f"/e/{panel['id']}/form").data.decode()
    # A switch that fails takes the networks it carries with it.
    tree = client.get(f"/api/entities/{sw['id']}/dependencies?direction=dependents").get_json()["tree"]
    assert {n["name"] for n in tree} == {"IoT", "Lab"}


def test_a_switch_takes_no_more_cables_than_its_ports(client, h, admin):
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch", "f.ports": 2})
    pcs = [make(client, h, "workstation", name=f"pc{i}") for i in range(3)]
    for pc in pcs[:2]:
        post(client, h, "/network/cables", device_id=pc["id"], other_device_id=sw["id"])
    tab = client.get(f"/e/{sw['id']}/sheet?tab=ports").data.decode()
    assert "2 of 2 ports cabled: give it more ports" in tab and "Connect a cable" not in tab
    # Full: refused, and no longer offered as the other end.
    error = post(client, h, "/network/cables", 400, device_id=pcs[2]["id"], other_device_id=sw["id"])["error"]
    assert error == "sw1 has 2 ports, and all of them are cabled. Give it more ports, or record its ports one by one."
    assert f'value="device:{sw["id"]}"' not in client.get(f"/e/{pcs[2]['id']}/sheet?tab=ports").data.decode()
    # More ports, or none recorded: it takes the cable.
    post(client, h, f"/api/entities/{sw['id']}", **{"f.ports": ""})
    post(client, h, "/network/cables", device_id=pcs[2]["id"], other_device_id=sw["id"])
    assert "3 cables." in client.get(f"/e/{sw['id']}/sheet?tab=ports").data.decode()
