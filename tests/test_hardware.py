"""The Hardware module: its types and fields, the rack position in its
forms, the warranty filters and card, and who may change it."""
from datetime import date, timedelta

from .conftest import make
from .test_locations import place


def test_a_server_with_its_specs(client, h, admin):
    server = make(client, h, "server", name="pve1", **{
        "f.manufacturer": "Dell", "f.model": "PowerEdge R730xd", "f.serial": "7XJ2K42", "f.kind": "rack",
        "f.cpu_cores": 28, "f.ram_gb": 128, "f.price": "850.50", "f.purchase_date": "2023-06-02"})
    assert server["status"] == "deployed" and server["status_label"] == "Deployed"
    assert server["fields"]["ram_gb"] == 128 and server["fields"]["price"] == 850.5
    assert server["fields"]["purchase_date"] == "2023-06-02"
    # Search finds the serial; the list row shows the make and model.
    assert [e["name"] for e in client.get("/api/entities?q=7xj2k42").get_json()["entities"]] == ["pve1"]
    row = client.get("/hardware?view=list").data.decode()
    assert "Dell" in row and "PowerEdge R730xd" in row
    card = client.get("/hardware?view=cards").data.decode()
    assert "128 GB" in card
    sheet = client.get(f"/e/{server['id']}/sheet").data.decode()
    assert ">Purchase</p>" in sheet and ">Specs</p>" in sheet and "Rack mount" in sheet
    bad = client.post("/api/entities", json={"type": "server", "name": "x", "f.ram_gb": "lots"}, headers=h)
    assert "whole number" in bad.get_json()["error"]
    lifecycle = client.post(f"/api/entities/{server['id']}", json={"status": "in_repair"}, headers=h).get_json()
    assert lifecycle["entity"]["status_label"] == "In repair"


def test_every_type_has_a_form(client, h, admin):
    for key in ("server", "network_device", "firewall", "access_point", "ups", "nas", "workstation",
                "printer", "peripheral"):
        form = client.get(f"/e/form?type={key}").data.decode()
        assert 'name="f.warranty_until"' in form, key
        # What goes in a rack has the rack position; the rest don't.
        assert ('name="s.rack.rack_id"' in form) == (key not in ("access_point", "workstation", "printer")), key


def test_a_device_goes_in_a_rack_from_its_form(client, h, admin):
    site, building, room, rack = place(client, h)
    switch = make(client, h, "network_device", name="sw-core", location_id=room["id"], **{
        "f.kind": "switch", "f.ports": 24, "s.rack.rack_id": rack["id"], "s.rack.position_u": 12})
    assert switch["location"]["id"] == rack["id"]
    elevation = client.get(f"/locations/racks/{rack['id']}/elevation").get_json()
    assert [(m["name"], m["position_u"]) for m in elevation["mounts"]] == [("sw-core", 12)]
    sheet = client.get(f"/e/{switch['id']}/sheet?tab=position").data.decode()
    assert "U12" in sheet and "Front" in sheet


def warranty(client, h, name, days, status="deployed"):
    return make(client, h, "server", name=name, status=status,
                **{"f.warranty_until": (date.today() + timedelta(days=days)).isoformat()})


def test_warranty_filters_and_card(client, h, admin):
    warranty(client, h, "soon", 30)
    warranty(client, h, "later", 400)
    warranty(client, h, "over", -10)
    warranty(client, h, "gone", -10, status="disposed")
    soon = client.get("/hardware?f=warranty_soon&view=list").data.decode()
    assert ">soon<" in soon and ">later<" not in soon and ">over<" not in soon
    over = client.get("/hardware?f=warranty_over&view=list").data.decode()
    assert ">over<" in over and ">gone<" not in over
    sidebar = client.get("/hardware").data.decode()
    assert "Warranty ending soon" in sidebar and "Out of warranty" in sidebar
    page = client.get("/").data.decode()
    card = page.split('id="coming-up"')[1].split('<div class="card widget')[0]
    assert "in 30 days" in card and "10 days ago" in card and ">gone<" not in card and ">later<" not in card
    assert 'class="count count--alert" title="2 dates coming up or just past">2<' in page


def test_viewers_read_hardware_but_cannot_change_it(client, h, admin, viewer):
    server = make(client, h, "server", name="pve1")
    other, oh = viewer
    assert other.get(f"/api/entities/{server['id']}").status_code == 200
    assert other.post("/api/entities", json={"type": "server", "name": "x"}, headers=oh).status_code == 403
    assert other.post(f"/api/entities/{server['id']}", json={"name": "y"}, headers=oh).status_code == 403
    assert other.get("/e/form?type=server").status_code == 403


def test_hardware_is_off_while_locations_is(app, client, h, admin):
    server = make(client, h, "server", name="pve1")
    client.post("/admin/modules/locations", json={"enabled": False}, headers=h)
    assert client.get("/hardware").status_code == 404
    assert client.get(f"/api/entities/{server['id']}").status_code == 404
    refused = client.post("/admin/modules/hardware", json={"enabled": True}, headers=h)
    assert "needs Locations" in refused.get_json()["error"]
    client.post("/admin/modules/locations", json={"enabled": True}, headers=h)
    assert client.get(f"/api/entities/{server['id']}").get_json()["entity"]["name"] == "pve1"


def test_the_demo_puts_the_equipment_in_the_rack(client, h, admin):
    client.post("/admin/seed-demo", headers=h)
    rack = client.get("/api/entities?type=rack").get_json()["entities"][0]
    elevation = client.get(f"/locations/racks/{rack['id']}/elevation").get_json()
    names = {m["name"] for m in elevation["mounts"]}
    assert {"ups1", "pdu1", "sw-core", "edge-fw", "srv1", "nas1", "Rack shelf"} <= names
    assert elevation["conflicts"] == []
    ups = client.get("/api/entities?type=ups").get_json()["entities"][0]
    tree = client.get(f"/api/entities/{ups['id']}/dependencies").get_json()["tree"]
    assert {"srv1", "nas1", "sw-core"} <= {n["name"] for n in tree}
    outage = client.get("/api/entities?type=document&q=outage").get_json()["entities"][0]
    assert "<s>" not in client.get(f"/e/{outage['id']}/sheet").data.decode()


def test_a_whole_price_reads_as_one_in_the_form(client, h, admin):
    server = make(client, h, "server", name="pve1", **{"f.price": 850})
    assert 'name="f.price" value="850"' in client.get(f"/e/{server['id']}/form").data.decode()
