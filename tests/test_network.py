"""The Network module: subnets, VLANs and IP addresses with their checks,
the addresses section and tab on other records, the subnet view, ports and
cables with tracing, DNS records, search, filters and roles."""
from datetime import date, timedelta

from .conftest import make


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
    assert "two addresses with a dash" in error(client, h, "subnet", name="x",
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


def test_viewers_see_ports_but_cannot_change_them(client, h, admin, viewer):
    switch, panel, pc, ports = rack(client, h)
    other, oh = viewer
    assert other.get(f"/network/devices/{switch['id']}/ports").status_code == 200
    assert other.get(f"/network/ports/{ports['sw1 Port 1']['id']}/trace").status_code == 200
    for url, body in ((f"/network/devices/{switch['id']}/ports", {}), ("/network/cables", {}),
                      (f"/network/ports/{ports['sw1 Port 1']['id']}/delete", {}), ("/network/ports/edit", {})):
        assert other.post(url, json=body, headers=oh).status_code == 403, url
    tab = other.get(f"/e/{switch['id']}/sheet?tab=ports").data.decode()
    assert "Add ports" not in tab and "data-api-post" not in tab


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


def test_network_off_hides_its_parts_on_other_records(client, h, admin):
    server = make(client, h, "server", name="srv1")
    client.post("/admin/modules/network", json={"enabled": False}, headers=h)
    assert "s.addresses" not in client.get("/e/form?type=server").data.decode()
    sheet = client.get(f"/e/{server['id']}/sheet").data.decode()
    assert "Ports" not in sheet.split('class="tabs"')[1].split("</nav>")[0]
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
