"""The network diagram and each record's Neighborhood tab, and the module
pages they hang on."""
import re

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


def test_where_the_internet_comes_in_is_drawn_first(client, h, admin):
    # A router the line comes in at, cabled to a modem with none: the router is drawn above, marked.
    router = make(client, h, "network_device", name="gw", **{"f.kind": "router", "s.internet.line": True})
    modem = make(client, h, "network_device", name="old-modem", **{"f.kind": "modem"})
    client.post("/network/cables", json={"device_id": modem["id"], "other_device_id": router["id"]}, headers=h)
    page = client.get("/p/diagram/network").data.decode()
    assert page.count('class="diagram-node') == 2 and page.index(">gw<") < page.index(">old-modem<")
    assert "Internet comes in" in page


def test_two_internet_lines_are_drawn_side_by_side(client, h, admin):
    # A modem for each ISP, both into one firewall: both in the top row, the firewall below them.
    fiber = make(client, h, "network_device", name="fiber-modem", **{"f.kind": "modem", "s.internet.line": True})
    lte = make(client, h, "network_device", name="lte-modem", **{"f.kind": "modem", "s.internet.line": True})
    fw = make(client, h, "firewall", name="fw")
    for m in (fiber, lte):
        client.post("/network/cables", json={"device_id": fw["id"], "other_device_id": m["id"]}, headers=h)
    page = client.get("/p/diagram/network").data.decode()
    at = {}
    for box in page.split('class="diagram-node')[1:]:
        x, y = map(float, re.search(r'translate\(([\d.]+) ([\d.]+)\)', box).groups())
        at[re.search(r'class="diagram-name"[^>]*>([^<]+)<', box).group(1)] = (x, y)
    assert at["fiber-modem"][1] == at["lte-modem"][1] < at["fw"][1]          # one row, the firewall below
    assert float(at["fiber-modem"][0]) < float(at["fw"][0]) < float(at["lte-modem"][0])


def test_two_wireless_bridges_are_joined_by_a_dotted_line(client, h, admin):
    a = make(client, h, "network_device", name="Bridge house", **{"f.kind": "bridge"})
    b = make(client, h, "network_device", name="Bridge garage", **{"f.kind": "bridge"})
    client.post(f"/api/entities/{a['id']}", json={"s.bridge.other": b["id"]}, headers=h)
    page = client.get("/p/diagram/network").data.decode()
    assert page.count('class="diagram-node') == 2 and 'diagram-link--wireless' in page
    assert "a dotted one is a wireless link between two bridges" in page
    assert "Bridge house to Bridge garage, a wireless link" in page or "Bridge garage to Bridge house" in page


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


def test_a_box_shows_the_record_in_brief_as_the_pointer_rests_on_it(client, h, admin, viewer):
    site = make(client, h, "site", name="Home")
    isp = make(client, h, "vendor", name="Springfield Cable")
    modem = make(client, h, "network_device", name="modem", location_id=site["id"],
                 tags=["edge"], notes="In bridge mode.",
                 **{"f.kind": "modem", "f.model": "S33", "f.managed": False, "s.addresses.list": "192.168.100.1",
                    "s.supplier.vendor_id": isp["id"], "s.internet.line": True, "s.internet.circuit_id": "SC-1"})
    fw = make(client, h, "firewall", name="fw")
    client.post("/network/cables", json={"device_id": modem["id"], "other_device_id": fw["id"]}, headers=h)
    page = client.get("/p/diagram/network").data.decode()
    assert f'data-entity="{modem["id"]}" data-peek aria-label="modem, Internet comes in"' in page
    other, _ = viewer
    card = other.get(f"/e/{modem['id']}/peek").data.decode()
    assert '<p class="peek-name">modem</p>' in card and "Network device · Deployed" in card
    assert '<p class="peek-path">Home</p>' in card
    for label, text in (("Kind", "Modem"), ("Model", "S33"), ("IP addresses", "192.168.100.1"),
                        ("Supplier", "Springfield Cable"), ("Circuit ID", "SC-1")):
        assert f"<dt>{label}</dt><dd>{text}</dd>" in card, label
    assert "<dt>Managed</dt>" not in card and "<dt>Contract</dt>" not in card     # nothing to say
    assert '<span class="tagchip">edge</span>' in card and "In bridge mode." in card


def test_the_diagram_draws_a_building_a_network_or_the_whole_site(client, h, admin):
    site = make(client, h, "site", name="Campus")
    main = make(client, h, "building", name="Main", location_id=site["id"])
    annex = make(client, h, "building", name="Annex", location_id=site["id"])
    servers = make(client, h, "vlan", name="Servers", location_id=main["id"], **{"f.vid": 20})
    make(client, h, "subnet", name="Servers LAN", location_id=main["id"],
         **{"f.cidr": "10.0.20.0/24", "f.vlan": servers["id"]})
    guest = make(client, h, "subnet", name="Guest", location_id=annex["id"], **{"f.cidr": "10.9.0.0/24"})
    fw = make(client, h, "firewall", name="fw", location_id=main["id"],
              **{"s.networks.list": f"{servers['id']},{guest['id']}"})
    srv = make(client, h, "server", name="srv", location_id=main["id"], **{"s.addresses.list": "10.0.20.5"})
    sw = make(client, h, "network_device", name="sw-annex", location_id=annex["id"], **{"f.kind": "switch"})
    pc = make(client, h, "workstation", name="guest-pc", location_id=annex["id"], **{"s.addresses.list": "10.9.0.7"})
    for a, b in ((srv, fw), (sw, fw), (pc, sw)):
        client.post("/network/cables", json={"device_id": a["id"], "other_device_id": b["id"]}, headers=h)
    page = client.get("/p/diagram/network").data.decode()
    seg = page.split('class="seg seg--links"')[1].split("</nav>")[0]
    # Buildings, then networks (a VLAN, a subnet on none; not the VLAN's own subnet), then the whole site.
    assert re.findall(r">([^<]+)</a>", seg) == ["Annex", "Main", "Guest", "Servers", "Whole site"]
    assert 'class="is-active" aria-current="page">Whole site<' in seg
    names = lambda html: set(re.findall(r'class="diagram-name"[^>]*>([^<]+)<', html))
    assert names(page) == {"fw", "srv", "sw-annex", "guest-pc"}
    url = lambda part: f"/p/diagram/network?part={part}&site={site['id']}"
    # A building: its devices, and what they are cabled to one step beyond (the firewall in Main).
    assert names(client.get(url(f"b{annex['id']}")).data.decode()) == {"sw-annex", "guest-pc", "fw"}
    # A network: the devices on it and the gear carrying it, linked to each other only, and what
    # joins them on the way to the most upstream of them.
    assert names(client.get(url(f"n{servers['id']}")).data.decode()) == {"fw", "srv"}
    # The switch between them carries it without saying so: drawn too, joining the PC to the firewall.
    assert names(client.get(url(f"n{guest['id']}")).data.decode()) == {"fw", "sw-annex", "guest-pc"}
    # One site: no site choice; a second one with equipment brings it, and All sites.
    assert 'class="field diagram-site"' not in page
    cabin = make(client, h, "site", name="Cabin")
    a = make(client, h, "network_device", name="cabin-sw", location_id=cabin["id"], **{"f.kind": "switch"})
    b = make(client, h, "workstation", name="cabin-pc", location_id=cabin["id"])
    client.post("/network/cables", json={"device_id": a["id"], "other_device_id": b["id"]}, headers=h)
    page = client.get(f"/p/diagram/network?site={cabin['id']}").data.decode()
    assert '<option value="/p/diagram/network?site=0" >All sites</option>' in page
    assert names(page) == {"cabin-sw", "cabin-pc"}
