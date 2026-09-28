"""The network diagram and each record's Neighborhood tab, and the module
pages they hang on."""
from .conftest import make
from .test_network import post, rack


def test_the_diagram_draws_cables_through_patch_panels(client, h, admin):
    switch, panel, pc, ports = rack(client, h)
    modem = make(client, h, "network_device", name="modem", **{"f.kind": "modem"})
    post(client, h, "/network/cables", port_id=ports["pc eth0"]["id"], other_id=ports["pp1 Rear 1"]["id"])
    post(client, h, "/network/cables", port_id=ports["pp1 Front 1"]["id"], other_id=ports["sw1 Port 3"]["id"])
    client.post("/api/relationships", json={"kind": "connected_to", "source_id": modem["id"],
                                            "target_id": switch["id"], "note": "WAN"}, headers=h)
    page = client.get("/p/diagram/network").data.decode()
    assert page.count('class="diagram-node') == 3          # the panel is on the way, not a box
    assert "data-zoom" in page and "data-zoom-fit" in page
    assert "pc eth0 to sw1 Port 3 through pp1" in page or "sw1 Port 3 to pc eth0 through pp1" in page
    assert "diagram-link--loose" in page and "linked but no cable recorded" in page
    # The modem is upstream: drawn first, above the switch.
    assert page.index(">modem<") < page.index(">sw1<") < page.index(">pc<")
    sidebar = client.get("/").data.decode()
    assert 'href="/p/diagram/network"' in sidebar


def test_an_empty_network_says_what_to_do(client, h, admin):
    assert "No cables yet" in client.get("/p/diagram/network").data.decode()


def test_a_record_shows_its_neighborhood(client, h, admin):
    host = make(client, h, "hypervisor", name="pve1")
    vm = make(client, h, "vm", name="docker1", **{"f.host": host["id"]})
    lonely = make(client, h, "vm", name="spare")
    tab = client.get(f"/e/{host['id']}/sheet?tab=neighborhood").data.decode()
    assert ">docker1<" in tab and "runs" in tab and "is-center" in tab
    assert 'data-tab="neighborhood"' in client.get(f"/e/{vm['id']}/sheet").data.decode()
    assert 'data-tab="neighborhood"' not in client.get(f"/e/{lonely['id']}/sheet").data.decode()


def test_a_page_goes_with_its_module(client, h, admin):
    client.post("/admin/modules/diagram", json={"enabled": False}, headers=h)
    assert client.get("/p/diagram/network").status_code == 404
    assert 'href="/p/diagram/network"' not in client.get("/").data.decode()
    assert client.get("/p/network/nothing").status_code == 404


def test_viewers_see_the_diagram(client, h, admin, viewer):
    other, _ = viewer
    assert other.get("/p/diagram/network").status_code == 200
