"""Dependencies the cabling makes: a device needs the gear it is cabled to,
and gear the gear nearer the internet, without a link for each."""
from .conftest import make


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def tree(client, entity, direction):
    def flat(nodes, depth=0):
        for n in nodes:
            yield depth, n["label"], n["name"]
            yield from flat(n["children"], depth + 1)
    found = client.get(f"/api/entities/{entity['id']}/dependencies?direction={direction}").get_json()["tree"]
    return list(flat(found))


def cable(client, h, a, b, **more):
    post(client, h, "/network/cables", device_id=a["id"], other_device_id=b["id"], **more)


def network(client, h):
    d = {"wan": make(client, h, "network", name="Fiber", **{"f.kind": "wan"}),
         "modem": make(client, h, "network_device", name="modem", **{"f.kind": "modem"}),
         "fw": make(client, h, "firewall", name="fw"),
         "core": make(client, h, "network_device", name="core", **{"f.kind": "switch"}),
         "edge": make(client, h, "network_device", name="edge", **{"f.kind": "switch"}),
         "srv": make(client, h, "server", name="srv")}
    post(client, h, f"/api/entities/{d['wan']['id']}", **{"f.comes_in_at": d["modem"]["id"]})
    # Cabled the "wrong" way round, to show the direction comes from the network, not the cable.
    cable(client, h, d["fw"], d["modem"])
    cable(client, h, d["core"], d["fw"])
    cable(client, h, d["core"], d["edge"])
    cable(client, h, d["edge"], d["srv"])
    return d


def test_a_device_needs_the_gear_it_is_cabled_to_and_up_to_the_internet(client, h, admin):
    d = network(client, h)
    needs = tree(client, d["srv"], "dependencies")
    assert needs == [(0, "plugs into", "edge"), (1, "uplinks to", "core"), (2, "uplinks to", "fw"),
                     (3, "uplinks to", "modem")]
    # The line comes in at the modem: down with it, along with everything behind the modem.
    assert (0, "brings in", "Fiber") in tree(client, d["modem"], "dependents")
    # What breaks with the core switch: the edge switch, and what is plugged into that.
    assert tree(client, d["core"], "dependents") == [(0, "is the uplink for", "edge"), (1, "has plugged in", "srv")]
    # A VM on the server goes down with the switch too.
    host = make(client, h, "hypervisor", name="pve")
    post(client, h, "/api/relationships", source_id=host["id"], target_id=d["srv"]["id"], kind="runs_on")
    assert (1, "runs", "pve") in tree(client, d["edge"], "dependents")


def test_a_cable_through_a_patch_panel_counts_from_end_to_end(client, h, admin):
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    panel = make(client, h, "network_device", name="pp1", **{"f.kind": "patch_panel"})
    pc = make(client, h, "workstation", name="pc")
    post(client, h, f"/network/devices/{panel['id']}/ports", first=1, last=1, rear=True)
    panel_ports = {p["name"]: p for p in client.get(f"/network/devices/{panel['id']}/ports").get_json()["ports"]}
    post(client, h, "/network/cables", device_id=pc["id"], other_id=panel_ports["Rear 1"]["id"], label="Jack 4")
    post(client, h, "/network/cables", device_id=sw["id"], other_id=panel_ports["Front 1"]["id"], label="20-01")
    assert tree(client, pc, "dependencies") == [(0, "plugs into", "sw1")]
    assert tree(client, panel, "dependents") == []
    # The Relationships tab lists it, read-only, with the panel and the labels.
    tab = client.get(f"/e/{pc['id']}/sheet?tab=relationships").data.decode()
    assert "cabled to" in tab and "through pp1" in tab and "cables Jack 4, 20-01" in tab
    assert "From the Cabling tab: change or remove the cable there." in tab
    assert "Not linked to anything yet" not in tab and "Remove this link" not in tab


def test_a_moca_pair_and_two_switches_at_the_same_depth(client, h, admin):
    d = network(client, h)
    near = make(client, h, "network_device", name="moca-a", **{"f.kind": "moca"})
    far = make(client, h, "network_device", name="moca-b", **{"f.kind": "moca", "s.moca.other": near["id"]})
    tv = make(client, h, "workstation", name="den-pc")
    cable(client, h, near, d["core"])
    cable(client, h, far, tv)
    assert tree(client, tv, "dependencies")[:3] == [
        (0, "plugs into", "moca-b"), (1, "gets the network over coax from", "moca-a"), (2, "uplinks to", "core")]
    # A second switch on the core, linked to the edge switch as well: neither needs the other.
    other = make(client, h, "network_device", name="edge2", **{"f.kind": "switch"})
    cable(client, h, other, d["core"])
    cable(client, h, other, d["edge"])
    assert (0, "uplinks to", "core") in tree(client, other, "dependencies")
    assert all(name != "edge" for _, _, name in tree(client, other, "dependencies"))


def test_a_link_saying_the_same_isnt_doubled_and_peers_need_nothing(client, h, admin):
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    srv = make(client, h, "server", name="srv")
    nas = make(client, h, "nas", name="nas")
    cable(client, h, srv, sw)
    cable(client, h, srv, sw)      # two cables, one dependency
    post(client, h, "/api/relationships", source_id=srv["id"], target_id=sw["id"], kind="depends_on")
    assert tree(client, srv, "dependencies") == [(0, "depends on", "sw1")]
    # A server and a NAS cabled to each other: shown, but neither needs the other.
    cable(client, h, srv, nas)
    assert tree(client, nas, "dependencies") == []
    assert "cabled to" in client.get(f"/e/{nas['id']}/sheet?tab=relationships").data.decode()


def test_a_ups_on_the_network_takes_nothing_down_with_the_switch(client, h, admin):
    sw = make(client, h, "network_device", name="sw1", **{"f.kind": "switch"})
    ups = make(client, h, "ups", name="ups1")
    srv = make(client, h, "server", name="srv")
    post(client, h, "/api/relationships", source_id=srv["id"], target_id=ups["id"], kind="powered_by")
    cable(client, h, ups, sw)
    # Managed over the network, it goes on powering the server without it.
    assert tree(client, sw, "dependents") == []
    assert "cabled to" in client.get(f"/e/{ups['id']}/sheet?tab=relationships").data.decode()
