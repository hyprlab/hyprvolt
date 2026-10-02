"""Cable labels from the network each cable is on: in the Cables step, in
Suggest cables, and for the cables with no label."""
import re

from .conftest import make


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def lab(client, h):
    site = make(client, h, "site", name="Home")
    vlan = make(client, h, "vlan", name="Servers", **{"f.vid": 20})
    servers = make(client, h, "subnet", name="Servers", **{"f.cidr": "10.0.20.0/24", "f.vlan": vlan["id"]})
    make(client, h, "subnet", name="Lab", **{"f.cidr": "192.168.50.0/24"})
    d = {"site": site, "vlan": vlan}

    def at(type_, name, **more):
        return make(client, h, type_, name=name, location_id=site["id"], **more)
    d["modem"] = at("network_device", "modem", **{"f.kind": "modem"})
    d["fw"] = at("firewall", "fw")
    d["sw"] = at("network_device", "sw1", **{"f.kind": "switch", "s.networks.list": str(servers["id"])})
    d["srv1"] = at("server", "srv1", **{"s.addresses.list": "10.0.20.5"})
    d["srv2"] = at("server", "srv2", **{"s.addresses.list": "10.0.20.6"})
    d["pc"] = at("workstation", "pc1", **{"s.addresses.list": "192.168.50.10"})
    d["cam"] = at("ip_camera", "cam1")
    return d


def cable_label(client, device):
    return client.get(f"/network/devices/{device['id']}/ports").get_json()["ports"][0]["cable"]["label"]


def test_a_cable_added_without_a_label_is_labeled_by_its_network(client, h, admin):
    d = lab(client, h)
    rows = f"/site-setup/cables/rows?site={d['site']['id']}"

    def connect(a, b, label=""):
        post(client, h, rows, values={"from": f"device:{d[a]['id']}", "to": f"device:{d[b]['id']}", "label": label})
    connect("srv1", "sw")
    connect("srv2", "sw")
    connect("pc", "sw")
    connect("cam", "sw")
    connect("sw", "fw")
    connect("modem", "fw")
    labels = {k: cable_label(client, d[k]) for k in ("srv1", "srv2", "pc", "cam", "modem")}
    # VLAN 20's first and second; the subnet with no VLAN by its third number; no network known.
    assert labels == {"srv1": "20-01", "srv2": "20-02", "pc": "50-01", "cam": "C-01", "modem": "WAN-01"}
    ends = client.get(f"/network/devices/{d['fw']['id']}/ports").get_json()["ports"]
    assert sorted(p["cable"]["label"] for p in ends) == ["UP-01", "WAN-01"]
    # A label given is kept.
    srv3 = make(client, h, "server", name="srv3", location_id=d["site"]["id"], **{"s.addresses.list": "10.0.20.7"})
    post(client, h, rows, values={"from": f"device:{srv3['id']}", "to": f"device:{d['sw']['id']}", "label": "R1-07"})
    assert cable_label(client, srv3) == "R1-07"


def test_the_switch_ports_vlan_comes_first(client, h, admin):
    d = lab(client, h)
    iot = make(client, h, "vlan", name="IoT", **{"f.vid": 30})
    post(client, h, f"/network/devices/{d['sw']['id']}/ports", prefix="Port ", first=1, last=2)
    port = client.get(f"/network/devices/{d['sw']['id']}/ports").get_json()["ports"][0]
    post(client, h, f"/network/ports/{port['id']}", vlan_id=iot["id"])
    post(client, h, f"/site-setup/cables/rows?site={d['site']['id']}",
         values={"from": f"device:{d['srv1']['id']}", "to": f"port:{port['id']}"})
    assert cable_label(client, d["srv1"]) == "30-01"


def test_the_cables_with_no_label_are_labeled_from_the_step(client, h, admin):
    d = lab(client, h)
    for k in ("srv1", "pc"):
        post(client, h, "/network/cables", device_id=d[k]["id"], other_device_id=d["sw"]["id"])
    page = client.get(f"/site-setup/cables?site={d['site']['id']}").data.decode()
    assert "Label the unlabeled cables" in page and "2 cables have no label" in page
    answer = post(client, h, "/network/cables/label", site=d["site"]["id"])
    assert answer["message"] == "Labeled 2 cables."
    assert (cable_label(client, d["srv1"]), cable_label(client, d["pc"])) == ("20-01", "50-01")
    assert "Label the unlabeled cables" not in client.get(f"/site-setup/cables?site={d['site']['id']}").data.decode()
    assert post(client, h, "/network/cables/label", site=d["site"]["id"])["message"] == \
        "Every cable has a label already."


def test_suggested_cables_come_labeled_in_turn(client, h, admin):
    d = lab(client, h)
    post(client, h, "/network/cables", device_id=d["srv1"]["id"], other_device_id=d["sw"]["id"], label="20-01")
    html = post(client, h, "/network/cables/suggest", site=d["site"]["id"])["html"]
    labels = {}
    for block in html.split('<li class="review-item">')[1:]:
        title = re.search(r"<span>([^<]+)</span>", block).group(1)
        labels[title] = re.search(r'name="label\d+" maxlength="60" value="([^"]*)"', block).group(1)
    assert labels["srv2 to sw1"] == "20-02"                 # after the one there already
    assert labels["modem to fw"] == "WAN-01" and labels["fw to sw1"] == "UP-01"
    assert labels["pc1 to sw1"] == "50-01" and labels["cam1 to sw1"] == "C-01"
