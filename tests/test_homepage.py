"""Services read from a Homepage dashboard's services.yaml (and docker.yaml),
each matched to what it runs on, reviewed, then imported."""
import io
import json
import re

from .conftest import make

SERVICES = b"""
- Media:
    - Sonarr:
        href: https://sonarr.example.com
        description: Series
        server: media
        container: sonarr
        widget:
          type: sonarr
          url: http://10.0.20.5:8989
          key: s3cr3t-api-key
    - Jellyfin:
        href: http://10.0.20.5:8096
        icon: jellyfin.png
- Network:
    - AdGuard Home:
        href: http://10.0.20.53
        proxmoxNode: pve1
        proxmoxVMID: 105
        proxmoxType: lxc
    - Mystery:
        href: http://192.168.99.9
- Tools:
    - Monitoring:
        - Grafana:
            siteMonitor: http://media-vm.lan:3000
            href: "{{HOMEPAGE_VAR_GRAFANA}}"
"""
DOCKER = b"""
media:
  host: 10.0.20.5
  port: 2375
"""


def homelab(client, h):
    srv = make(client, h, "server", name="srv1", **{"s.addresses.list": "10.0.20.2"})
    pve = make(client, h, "hypervisor", name="pve1", **{"f.host": srv["id"]})
    vm = make(client, h, "vm", name="media-vm", **{"f.host": pve["id"], "f.vmid": 104,
                                                  "s.addresses.list": "10.0.20.5"})
    dh = make(client, h, "docker_host", name="docker-media", **{"f.host": vm["id"]})
    sonarr = make(client, h, "container", name="sonarr", **{"f.host": dh["id"]})
    adguard = make(client, h, "lxc", name="adguard", **{"f.host": pve["id"], "f.vmid": 105,
                                                       "s.addresses.list": "10.0.20.53"})
    return {"vm": vm, "sonarr": sonarr, "adguard": adguard}


def read(client, h, services=SERVICES, docker=DOCKER, status=200):
    files = {"services": (io.BytesIO(services), "services.yaml"), "back": "/site-setup/services?site=1"}
    if docker:
        files["docker"] = (io.BytesIO(docker), "docker.yaml")
    resp = client.post("/services/homepage/read", data=files, headers=h, content_type="multipart/form-data")
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def items(html):
    """Each reviewed service: its title, chip and why, and its chosen host."""
    out = {}
    for block in html.split('<li class="review-item">')[1:]:
        name = re.search(r'<span class="review-title">([^<]+?) <span', block).group(1)
        chip = re.search(r'<span class="chip[^"]*">([^<]+)</span>', block).group(1)
        host = re.search(r'<select name="host\d+">.*?<option value="(\d+)" selected', block, re.S)
        why = re.search(r'<span class="review-why">(.*?)</span>', block, re.S).group(1)
        index = re.search(r'name="use(\d+)"', block).group(1)
        out[name] = {"chip": chip, "host": int(host.group(1)) if host else None, "why": " ".join(why.split()),
                     "i": index, "block": block}
    return out


def test_each_service_is_matched_to_what_it_runs_on(client, h, admin):
    lab = homelab(client, h)
    got = items(read(client, h)["html"])
    # The container on the Docker server docker.yaml places at the VM's address.
    assert got["Sonarr"]["chip"] == "Matched" and got["Sonarr"]["host"] == lab["sonarr"]["id"]
    assert "the container sonarr on docker-media" in got["Sonarr"]["why"]
    # The Proxmox node and ID.
    assert got["AdGuard Home"]["chip"] == "Matched" and got["AdGuard Home"]["host"] == lab["adguard"]["id"]
    # Only its link points at the VM's address: likely, to check.
    assert got["Jellyfin"]["chip"] == "Check" and got["Jellyfin"]["host"] == lab["vm"]["id"]
    # A host name like a record's name, from a group in a group.
    assert got["Grafana"]["chip"] == "Check" and got["Grafana"]["host"] == lab["vm"]["id"]
    # Nothing points anywhere: to choose, saying what the file gave.
    assert got["Mystery"]["chip"] == "Choose" and got["Mystery"]["host"] is None
    assert "it gives the address 192.168.99.9" in got["Mystery"]["why"]
    # Those to choose come first; the API key is nowhere.
    html = read(client, h)["html"]
    assert html.index("Mystery") < html.index("Sonarr") and "s3cr3t" not in html


def test_the_reviewed_services_are_imported(client, h, admin):
    lab = homelab(client, h)
    make(client, h, "service", name="Jellyfin", **{"f.kind": "media"})
    html = read(client, h)["html"]
    got = items(html)
    form = {"count": len(got), "back": "/site-setup/services?site=1", "tag_groups": True}
    for name, row in got.items():
        i = row["i"]
        form[f"data{i}"] = json.loads(re.search(rf'name="data{i}" value="([^"]+)"', html).group(1)
                                      .replace("&#34;", '"').replace("&quot;", '"'))
        form[f"data{i}"] = json.dumps(form[f"data{i}"])
        form[f"use{i}"] = re.search(r'<option value="(\w+)" selected', row["block"]).group(1)
        form[f"host{i}"] = str(row["host"] or "")
        form[f"kind{i}"] = re.search(rf'name="kind{i}">.*?<option value="(\w+)" selected', html, re.S).group(1)
        form[f"ports{i}"] = re.search(rf'name="ports{i}" value="([^"]*)"', html).group(1)
    form[f"use{got['Mystery']['i']}"] = "skip"
    resp = client.post("/services/homepage/import", json=form, headers=h)
    assert resp.status_code == 200, resp.get_json()
    done = resp.get_json()["html"]
    assert "3 added, 1 updated, 1 left out" in done and 'href="/site-setup/services?site=1"' in done
    services = {e["name"]: client.get(f"/api/entities/{e['id']}").get_json()["entity"]
                for e in client.get("/api/entities?type=service").get_json()["entities"]}
    assert set(services) == {"Sonarr", "Jellyfin", "AdGuard Home", "Grafana"}
    sonarr = services["Sonarr"]
    assert sonarr["fields"]["host"] == lab["sonarr"]["id"] and sonarr["fields"]["kind"] == "downloads"
    assert sonarr["fields"]["url"] == "https://sonarr.example.com" and sonarr["fields"]["ports"] == "8989/tcp"
    assert sonarr["notes"] == "Series" and [t for t in sonarr["tags"]] == ["Media"]
    assert services["AdGuard Home"]["fields"]["kind"] == "adblock"
    assert services["Jellyfin"]["fields"]["host"] == lab["vm"]["id"]     # the recorded one, updated
    assert services["Grafana"]["fields"]["url"] in (None, "")             # {{HOMEPAGE_VAR_...}} isn't a link
    # Sonarr now runs on its container: the container's dependents include it.
    rels = client.get(f"/api/entities/{lab['sonarr']['id']}/relationships").get_json()["relationships"]
    assert any(r["other"]["name"] == "Sonarr" for r in rels)


def test_a_business_app_is_given_its_kind():
    from hyprvolt.modules.services.homepage import guess_kind
    for name, icon, kind in (("Odoo", "odoo.png", "erp"), ("Customers", "suitecrm.svg", "crm"),
                             ("Books", "akaunting.png", "accounting"), ("Tickets", "zammad.svg", "helpdesk"),
                             ("Snipe-IT", "", "inventory"), ("Jitsi Meet", "", "meetings")):
        assert guess_kind({"widget": "", "icon": icon, "name": name}) == kind, name


def test_files_that_arent_homepage_services_say_so(client, h, admin):
    assert "isn't valid YAML near line" in read(client, h, b"- a: [b", None, status=400)["error"]
    assert "No services found" in read(client, h, b"title: My homepage\nlayout: {}\n", None, status=400)["error"]
    assert "should list Docker servers" in read(client, h, SERVICES, b"- just a list", status=400)["error"]


def test_the_import_is_offered_in_the_guide_and_under_services(client, h, admin):
    client.post("/site-setup/site/rows", json={"values": {"name": "Home"}}, headers=h)
    page = client.get("/site-setup/services").data.decode()
    assert 'data-open="homepage-modal"' in page and 'id="homepage-modal"' in page
    assert 'name="back" value="/site-setup/services"' in page
    page = client.get("/p/services/homepage").data.decode()
    assert "services.yaml" in page and 'name="back" value="/services"' in page
