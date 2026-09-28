"""Changing a record's type: a device recorded as the wrong kind of
hardware, a VM that is really an LXC container, and what other modules
have attached to it that the new type couldn't keep."""
from .conftest import make
from .test_locations import mount, place, retype


def test_a_device_becomes_another_kind_with_its_specs(client, h, admin):
    srv = make(client, h, "server", name="store1", **{"f.cpu": "Xeon E-2236", "f.ram_gb": 64,
                                                      "f.serial": "SN123"})
    got = retype(client, h, srv, "nas")["entity"]
    assert got["type"] == "nas" and got["fields"]["cpu"] == "Xeon E-2236" and got["fields"]["ram_gb"] == 64
    assert got["fields"]["serial"] == "SN123"
    # Fields the NAS doesn't have are kept, and come back with the type.
    got = retype(client, h, srv, "ups")["entity"]
    assert "cpu" not in got["fields"]
    assert retype(client, h, srv, "server")["entity"]["fields"]["cpu"] == "Xeon E-2236"
    form = client.get(f"/e/{srv['id']}/form").data.decode()
    assert '<option value="nas" >NAS</option>' in form and '<option value="room"' not in form


def test_a_vm_becomes_an_lxc_container_on_the_same_host(client, h, admin):
    hv = make(client, h, "hypervisor", name="pve1")
    vm = make(client, h, "vm", name="pihole", **{"f.host": hv["id"], "f.vcpus": 2})
    got = retype(client, h, vm, "lxc")["entity"]
    assert got["type"] == "lxc" and got["fields"]["host"] == hv["id"] and got["fields"]["vcpus"] == 2
    assert "can't be changed into a container" in retype(client, h, vm, "container", 400)["error"]


def test_a_device_stays_a_host_while_something_runs_on_it(client, h, admin):
    srv = make(client, h, "server", name="docker1")
    make(client, h, "service", name="Plex", **{"f.host": srv["id"]})
    make(client, h, "hypervisor", name="pve1", **{"f.host": srv["id"]})
    error = retype(client, h, srv, "printer", 400)["error"]
    assert error.startswith("Plex and pve1 point at it (Runs on)") and "at a printer" in error
    # Another host is fine: the service still runs on it.
    assert retype(client, h, srv, "nas")["entity"]["type"] == "nas"


def test_software_and_rack_mounts_hold_a_device_to_its_kind(client, h, admin):
    site, building, room, rack = place(client, h)
    srv = make(client, h, "server", name="app1")
    title = make(client, h, "software", name="Nginx")
    resp = client.post("/software/installations", json={"software_id": title["id"], "host_id": srv["id"]},
                       headers=h)
    assert resp.status_code == 200, resp.get_json()
    assert "1 program is installed on it" in retype(client, h, srv, "printer", 400)["error"]
    ups = make(client, h, "ups", name="ups1")
    mount(client, h, rack, entity_id=ups["id"], position_u=1, height_u=2)
    assert "mounted in a rack" in retype(client, h, ups, "access_point", 400)["error"]
    assert retype(client, h, ups, "peripheral")["entity"]["type"] == "peripheral"


def test_an_ip_address_keeps_its_device_addressable(client, h, admin):
    hv = make(client, h, "hypervisor", name="pve1")
    vm = make(client, h, "vm", name="pihole", **{"f.host": hv["id"]})
    make(client, h, "ip_address", **{"f.address": "10.0.0.5", "f.assigned": vm["id"]})
    # Both kinds of guest are addressable: nothing to stop.
    assert retype(client, h, vm, "lxc")["entity"]["type"] == "lxc"
