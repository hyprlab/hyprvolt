"""The Virtual module: hosts kept as links, the dependency chain from the
hardware to the containers, the Guests and Containers tabs, the filter,
the widget and who may change it."""
from .conftest import make


def lab(client, h):
    server = make(client, h, "server", name="srv1", **{"f.cpu_cores": 8, "f.ram_gb": 32})
    cluster = make(client, h, "cluster", name="homelab", **{"f.platform": "proxmox"})
    pve = make(client, h, "hypervisor", name="pve1", **{"f.host": server["id"], "f.cluster": cluster["id"],
                                                          "f.platform": "proxmox"})
    return server, cluster, pve


def test_the_chain_from_hardware_to_containers(client, h, admin):
    server, cluster, pve = lab(client, h)
    vm = make(client, h, "vm", name="docker1", **{"f.host": pve["id"], "f.vcpus": 4, "f.memory_gb": 16})
    docker = make(client, h, "docker_host", name="Docker on docker1", **{"f.host": vm["id"]})
    stack = make(client, h, "stack", name="media", **{"f.host": docker["id"]})
    app = make(client, h, "container", name="jellyfin", **{"f.host": docker["id"], "f.stack": stack["id"],
                                                            "f.image": "jellyfin/jellyfin:10.9"})
    assert vm["fields"]["host"] == pve["id"] and app["fields"]["stack"] == stack["id"]
    # What breaks if the server goes down: everything, down to the container.
    tree = client.get(f"/api/entities/{server['id']}/dependencies").get_json()["tree"]

    def names(nodes):
        return {n["name"] for n in nodes} | {x for n in nodes for x in names(n.get("children", []))}
    assert {"pve1", "docker1", "Docker on docker1", "media", "jellyfin"} <= names(tree)
    # The cluster is only a grouping: nothing depends on it.
    assert client.get(f"/api/entities/{cluster['id']}/dependencies").get_json()["tree"] == []
    rels = client.get(f"/api/entities/{cluster['id']}/relationships").get_json()["relationships"]
    assert [(r["label"], r["other"]["name"]) for r in rels] == [("includes", "pve1")]
    # A VM has no place of its own; its host's hardware has one.
    no = client.post("/api/entities", json={"type": "vm", "name": "x", "location_id": server["id"]}, headers=h)
    assert no.status_code == 400
    # The host must be the right kind of record.
    wrong = client.post("/api/entities", json={"type": "vm", "name": "x", "f.host": server["id"]}, headers=h)
    assert "right type" in wrong.get_json()["error"]


def test_the_guests_tab_weighs_what_is_given_against_the_hardware(client, h, admin):
    server, cluster, pve = lab(client, h)
    make(client, h, "vm", name="big", **{"f.host": pve["id"], "f.vcpus": 6, "f.memory_gb": 24})
    make(client, h, "lxc", name="small", **{"f.host": pve["id"], "f.vcpus": 1, "f.memory_gb": 0.5})
    make(client, h, "vm", name="off", status="stopped", **{"f.host": pve["id"], "f.vcpus": 8, "f.memory_gb": 64})
    tab = client.get(f"/e/{pve['id']}/sheet?tab=guests").data.decode()
    assert "7/8 cores" in tab and "24.5/32 GB" in tab and "2 of 3 running" in tab
    assert ">over<" not in tab and ">srv1</a>" in tab
    assert 'data-new-type="vm" data-new-fields=\'{"host": ' + str(pve["id"]) + "}'" in tab
    sheet = client.get(f"/e/{pve['id']}/sheet").data.decode()
    assert 'Guests</span><span class="count">3</span>' in sheet
    # Starting the big one hands out more memory than there is.
    off = client.get("/api/entities?q=off&type=vm").get_json()["entities"][0]
    client.post(f"/api/entities/{off['id']}", json={"status": "running"}, headers=h)
    tab = client.get(f"/e/{pve['id']}/sheet?tab=guests").data.decode()
    assert "88.5/32 GB" in tab and ">over<" in tab
    # The cluster adds up its hosts.
    whole = client.get(f"/e/{cluster['id']}/sheet?tab=guests").data.decode()
    assert "15/8 cores" in whole and "on pve1" in whole
    # The dashboard card shows each hypervisor's memory.
    assert "88.5/32 GB" in client.get("/").data.decode().split(">Hypervisors</p>")[1]


def test_the_containers_tab_groups_by_stack(client, h, admin):
    server, cluster, pve = lab(client, h)
    docker = make(client, h, "docker_host", name="docker", **{"f.host": server["id"]})
    media = make(client, h, "stack", name="media", **{"f.host": docker["id"]})
    make(client, h, "stack", name="empty", **{"f.host": docker["id"]})
    make(client, h, "container", name="jellyfin", **{"f.host": docker["id"], "f.stack": media["id"],
                                                     "f.image": "jellyfin/jellyfin:10.9", "f.ports": "8096:8096"})
    make(client, h, "container", name="portainer", **{"f.host": docker["id"]})
    tab = client.get(f"/e/{docker['id']}/sheet?tab=containers").data.decode()
    assert tab.index(">media</a>") < tab.index("jellyfin/jellyfin:10.9 · 8096:8096") < tab.index("Not in a stack")
    assert "No containers in this stack yet." in tab and "portainer" in tab.split("Not in a stack")[1]
    stack_tab = client.get(f"/e/{media['id']}/sheet?tab=containers").data.decode()
    assert "jellyfin" in stack_tab and "portainer" not in stack_tab
    assert f"data-new-fields='{{\"host\": {docker['id']}, \"stack\": {media['id']}}}'" in stack_tab


def test_a_new_record_form_takes_preset_fields(client, h, admin):
    server, cluster, pve = lab(client, h)
    form = client.get(f"/e/form?type=vm&f.host={pve['id']}&f.vcpus=2").data.decode()
    assert f'<option value="{pve["id"]}" selected>' in form and 'name="f.vcpus" value="2"' in form


def test_records_without_a_host_are_listed(client, h, admin):
    server, cluster, pve = lab(client, h)
    make(client, h, "vm", name="placed", **{"f.host": pve["id"]})
    make(client, h, "vm", name="adrift")
    make(client, h, "vm", name="someday", status="planned")
    listed = client.get("/virtual?f=no_host&view=list").data.decode()
    assert ">adrift<" in listed and ">placed<" not in listed and ">someday<" not in listed
    # Deleting the host sets its guests adrift.
    client.post(f"/api/entities/{pve['id']}/delete", headers=h)
    assert ">placed<" in client.get("/virtual?f=no_host&view=list").data.decode()


def test_virtual_needs_hardware_and_viewers_cannot_change_it(client, h, admin, viewer):
    server, cluster, pve = lab(client, h)
    other, oh = viewer
    assert other.post("/api/entities", json={"type": "vm", "name": "x"}, headers=oh).status_code == 403
    assert other.get(f"/e/{pve['id']}/sheet?tab=guests").status_code == 200
    assert 'data-new-type="vm"' not in other.get(f"/e/{pve['id']}/sheet?tab=guests").data.decode()
    client.post("/admin/modules/hardware", json={"enabled": False}, headers=h)
    assert client.get("/virtual").status_code == 404
    client.post("/admin/modules/hardware", json={"enabled": True}, headers=h)
    assert client.get("/virtual").status_code == 200


def test_the_demo_runs_from_the_ups_to_the_containers(client, h, admin):
    client.post("/admin/seed-demo", headers=h)
    ups = client.get("/api/entities?type=ups").get_json()["entities"][0]
    tree = client.get(f"/api/entities/{ups['id']}/dependencies?depth=10").get_json()["tree"]

    def names(nodes):
        return {n["name"] for n in nodes} | {x for n in nodes for x in names(n.get("children", []))}
    assert {"srv1", "pve1", "docker1", "jellyfin", "pihole"} <= names(tree)
    outage = client.get("/api/entities?type=document&q=outage").get_json()["entities"][0]
    body = client.get(f"/e/{outage['id']}/sheet").data.decode()
    pve1 = client.get("/api/entities?type=hypervisor&q=pve1").get_json()["entities"][0]
    assert f'href="/e/{pve1["id"]}"' in body and "<s>" not in body
