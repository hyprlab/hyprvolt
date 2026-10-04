"""Software, Services, and Contacts and vendors: installations and seats,
services and what they run on, suppliers and contracts."""
import re
from datetime import date, timedelta

from .conftest import make


def listed(client, url):
    """A page without the New record window, whose kinds (DNS, Lease) would
    match a record's name."""
    return client.get(url).data.decode().split('id="entity-modal"')[0]


def post(client, h, url, status=200, **body):
    resp = client.post(url, json=body, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def history(client, entity_id):
    return client.get(f"/api/entities/{entity_id}/history").get_json()["history"]


def tree_names(nodes):
    return {n["name"] for n in nodes} | {x for n in nodes for x in tree_names(n.get("children", []))}


# ———— Software ————

def lab(client, h):
    title = make(client, h, "software", name="Proxmox VE", **{"f.current_version": "8.2.4", "f.category": "os"})
    srv = make(client, h, "server", name="srv1")
    nuc = make(client, h, "server", name="nuc1")
    return title, srv, nuc


def test_installations_are_recorded_with_their_version(client, h, admin):
    title, srv, nuc = lab(client, h)
    first = post(client, h, "/software/installations", software_id=title["id"], host_id=srv["id"], version="8.2.4")
    post(client, h, "/software/installations", software_id=title["id"], host_id=nuc["id"], version="8.2.2")
    again = post(client, h, "/software/installations", 400, software_id=title["id"], host_id=srv["id"])
    assert "already recorded on srv1" in again["error"]
    site = make(client, h, "site", name="Home")
    assert "where it is installed" in post(client, h, "/software/installations", 400, software_id=title["id"],
                                           host_id=site["id"])["error"]
    tab = client.get(f"/e/{title['id']}/sheet?tab=installations").data.decode()
    assert "nuc1</a> 8.2.2" in tab and tab.count(">behind<") == 1 and "The current version is 8.2.4." in tab
    host_tab = client.get(f"/e/{srv['id']}/sheet?tab=software").data.decode()
    assert "Proxmox VE</a> 8.2.4" in host_tab
    assert ">Proxmox VE<" in client.get("/software?f=outdated&view=list").data.decode()
    # A change shows in both histories; Undo brings back a removed one.
    iid = first["installation"]["id"]
    post(client, h, "/software/installations/edit", installation_id=iid, version="8.3.0")
    assert history(client, srv["id"])[0]["changes"] == [
        {"field": "install", "label": "Proxmox VE", "old": "8.2.4", "new": "8.3.0"}]
    assert history(client, title["id"])[0]["changes"][0]["label"] == "srv1"
    undo = post(client, h, f"/software/installations/{iid}/delete")["undo"]
    assert len(client.get(f"/software/titles/{title['id']}/installations").get_json()["installations"]) == 1
    post(client, h, undo["url"], **undo["body"])
    got = client.get(f"/software/hosts/{srv['id']}/installations").get_json()["installations"]
    assert [(i["software"], i["version"]) for i in got] == [("Proxmox VE", "8.3.0")]


def test_license_seats_are_counted(client, h, admin):
    title, srv, nuc = lab(client, h)
    other = make(client, h, "software", name="Other")
    lic = make(client, h, "license", name="Office key", **{"f.software": title["id"], "f.seats": 1, "f.extra_seats": 0})
    wrong = make(client, h, "license", name="Other key", **{"f.software": other["id"]})
    post(client, h, "/software/installations", software_id=title["id"], host_id=srv["id"], license_id=lic["id"])
    mismatch = post(client, h, "/software/installations", 400, software_id=title["id"], host_id=nuc["id"],
                    license_id=wrong["id"])
    assert "license for other software" in mismatch["error"]
    assert ">Office key<" not in client.get("/software?f=over&view=list").data.decode()
    post(client, h, "/software/installations", software_id=title["id"], host_id=nuc["id"], license_id=lic["id"])
    tab = client.get(f"/e/{lic['id']}/sheet?tab=seats").data.decode()
    assert "2/1 used" in tab and ">over<" in tab
    assert ">Office key<" in client.get("/software?f=over&view=list").data.decode()
    client.post(f"/api/entities/{lic['id']}", json={"f.seats": 5, "f.extra_seats": 2}, headers=h)
    tab = client.get(f"/e/{lic['id']}/sheet?tab=seats").data.decode()
    assert "4/5 used" in tab and "and 2 used elsewhere" in tab
    soon = (date.today() + timedelta(days=30)).isoformat()
    client.post(f"/api/entities/{lic['id']}", json={"f.renews": soon}, headers=h)
    assert ">Office key<" in client.get("/software?f=renewal&view=list").data.decode()
    assert "license for other software" not in client.get(f"/e/{title['id']}/sheet?tab=installations").data.decode()


def test_viewers_see_software_but_cannot_change_it(client, h, admin, viewer):
    title, srv, nuc = lab(client, h)
    other, oh = viewer
    assert other.post("/software/installations", json={"software_id": title["id"], "host_id": srv["id"]},
                      headers=oh).status_code == 403
    assert other.get(f"/software/titles/{title['id']}/installations").status_code == 200
    assert "Record an installation" not in other.get(f"/e/{title['id']}/sheet?tab=installations").data.decode()


# ———— Services ————

def test_a_service_runs_on_a_host_and_depends_on_its_domain(client, h, admin):
    server = make(client, h, "server", name="srv1")
    vm = make(client, h, "vm", name="docker1")
    domain = make(client, h, "domain", name="example.net")
    site = make(client, h, "site", name="Home")
    svc = make(client, h, "service", name="Website", **{"f.host": vm["id"], "f.domain": domain["id"],
                                                        "f.url": "https://example.net"})
    assert svc["fields"]["criticality"] == "normal" and svc["status_label"] == "Running"
    assert "right type" in client.post("/api/entities", json={"type": "service", "name": "x", "f.host": site["id"]},
                                       headers=h).get_json()["error"]
    client.post(f"/api/entities/{vm['id']}", json={"f.host": None}, headers=h)
    make(client, h, "hypervisor", name="pve1", **{"f.host": server["id"]})
    pve = client.get("/api/entities?type=hypervisor").get_json()["entities"][0]
    client.post(f"/api/entities/{vm['id']}", json={"f.host": pve["id"]}, headers=h)
    # What breaks if the server goes down, or the domain lapses.
    assert "Website" in tree_names(client.get(f"/api/entities/{server['id']}/dependencies").get_json()["tree"])
    assert "Website" in tree_names(client.get(f"/api/entities/{domain['id']}/dependencies").get_json()["tree"])
    form = client.get("/e/form?type=service").data.decode()
    # Runs on lists each kind of host under its own heading.
    runs_on = form.split('name="f.host"')[1].split("</select>")[0]
    assert re.search(r'<optgroup label="Virtual machines"><option value="\d+" >docker1</option>', runs_on)
    assert ">example.net</option>" in form and ">Home<" not in runs_on


def test_a_service_kind_is_chosen_under_its_heading(client, h, admin):
    form = client.get("/e/form?type=service").data.decode()
    network = form.split('<optgroup label="Network">')[1].split("</optgroup>")[0]
    assert '<option value="dhcp" >DHCP</option>' in network and ">Reverse proxy<" in network
    assert '<option value="ddns" >Dynamic DNS</option>' in network
    assert form.index('label="Apps"') < form.index('<option value="other" >Other</option>')
    dhcp = make(client, h, "service", name="Kea", **{"f.kind": "dhcp"})
    assert client.get(f"/api/entities/{dhcp['id']}").get_json()["entity"]["fields"]["kind"] == "dhcp"
    # The New record window finds it by the kind.
    assert 'data-kind-type="service" data-kind="dhcp"' in client.get("/").data.decode()


def test_a_service_address_can_be_an_ip_address_or_hostname(client, h, admin):
    for address in ("192.168.1.1", "192.168.1.1:67", "[fd00::1]:53", "router.lab:8443/admin", "https://dhcp.lab"):
        made = make(client, h, "service", name=f"DHCP {address}", **{"f.kind": "dhcp", "f.url": address})
        assert client.get(f"/api/entities/{made['id']}").get_json()["entity"]["fields"]["url"] == address
    bad = client.post("/api/entities", json={"type": "service", "name": "X", "f.url": "not an address"}, headers=h)
    assert bad.status_code == 400 and "IP address or hostname" in bad.get_json()["error"]
    gopher = client.post("/api/entities", json={"type": "service", "name": "Y", "f.url": "gopher://x"}, headers=h)
    assert gopher.status_code == 400


def test_services_that_matter_show_on_the_dashboard(client, h, admin):
    make(client, h, "service", name="DNS", **{"f.criticality": "critical"})
    make(client, h, "service", name="Backups", status="degraded", **{"f.criticality": "low"})
    make(client, h, "service", name="Grafana")
    card = client.get("/").data.decode().split('<p class="setting-label">Services</p>')[1].split("</section>")[0]
    assert card.index(">Backups<") < card.index(">DNS<") and ">Grafana<" not in card and "Degraded" in card
    assert ">DNS<" in listed(client, "/services?f=important&view=list")
    trouble = listed(client, "/services?f=trouble&view=list")
    assert ">Backups<" in trouble and ">DNS<" not in trouble


# ———— Contacts and vendors ————

def test_vendors_people_and_their_numbers(client, h, admin):
    vendor = make(client, h, "vendor", name="Dell", **{"f.support_phone": "+1 555 010 0142 ext 7",
                                                       "f.support_email": "help@dell.example"})
    # A phone number is kept as written; what can be dialed is a tel: link,
    # a vanity number's letters on their keys.
    verizon = make(client, h, "vendor", name="Verizon", **{"f.support_phone": "1-833-VERIZON"})
    loose = make(client, h, "vendor", name="Loose", **{"f.support_phone": "call Sam at the desk"})
    assert verizon["fields"]["support_phone"] == "1-833-VERIZON"
    assert 'href="tel:18338374966"' in client.get(f"/e/{verizon['id']}/sheet").data.decode()
    assert "tel:" not in client.get(f"/e/{loose['id']}/sheet").data.decode()
    sheet = client.get(f"/e/{vendor['id']}/sheet").data.decode()
    assert 'href="tel:+15550100142"' in sheet and 'href="mailto:help@dell.example"' in sheet
    assert 'href="tel:+15550100142" target' not in sheet
    person = make(client, h, "person", name="Dana", **{"f.organization": vendor["id"], "f.role": "Account manager"})
    assert person["fields"]["organization"] == vendor["id"]
    tab = client.get(f"/e/{vendor['id']}/sheet?tab=supplies").data.decode()
    assert ">Dana</a>" in tab and "Account manager" in tab


def test_the_supplier_section_links_a_vendor_and_a_contract(client, h, admin):
    vendor = make(client, h, "vendor", name="Synology")
    other = make(client, h, "vendor", name="Ubiquiti")
    contract = make(client, h, "contract", name="Warranty Plus", **{"f.vendor": vendor["id"], "f.kind": "warranty"})
    form = client.get("/e/form?type=nas").data.decode()
    assert 'name="s.supplier.vendor_id"' in form and "Warranty Plus · Synology" in form
    assert "s.supplier" not in client.get("/e/form?type=site").data.decode()
    nas = make(client, h, "nas", name="nas1", **{"s.supplier.vendor_id": vendor["id"],
                                                 "s.supplier.contract_id": contract["id"]})
    rels = {(r["kind"], r["other"]["name"]) for r in
            client.get(f"/api/entities/{nas['id']}/relationships").get_json()["relationships"]}
    assert rels == {("supplied_by", "Synology"), ("covered_by", "Warranty Plus")}
    assert ">nas1</a>" in client.get(f"/e/{vendor['id']}/sheet?tab=supplies").data.decode()
    assert ">nas1</a>" in client.get(f"/e/{contract['id']}/sheet?tab=covers").data.decode()
    client.post(f"/api/entities/{nas['id']}", json={"s.supplier.vendor_id": other["id"],
                                                    "s.supplier.contract_id": contract["id"]}, headers=h)
    assert history(client, nas["id"])[0]["changes"] == [
        {"field": "supplied_by", "label": "Supplier", "old": "Synology", "new": "Ubiquiti"}]
    assert f'<option value="{other["id"]}" selected>' in client.get(f"/e/{nas['id']}/form").data.decode()
    bad = client.post(f"/api/entities/{nas['id']}", json={"s.supplier.vendor_id": nas["id"]}, headers=h)
    assert "supplier that exists" in bad.get_json()["error"]


def test_contracts_say_when_they_end(client, h, admin):
    soon = make(client, h, "contract", name="Internet", **{"f.ends": (date.today() + timedelta(days=40)).isoformat(),
                                                           "f.notice_days": 30, "f.auto_renew": True})
    make(client, h, "contract", name="Lease", **{"f.ends": (date.today() + timedelta(days=400)).isoformat()})
    tab = client.get(f"/e/{soon['id']}/sheet?tab=covers").data.decode()
    assert "Renews in 40 days" in tab and "Notice is due by " + (date.today() + timedelta(days=10)).isoformat() in tab
    due = listed(client, "/contacts?f=ending&view=list")
    assert ">Internet<" in due and ">Lease<" not in due


def test_the_demo_operations(client, h, admin):
    client.post("/admin/seed-demo", headers=h)
    over = client.get("/software?f=over&view=list").data.decode()
    assert "Windows 11 Pro retail key" in over
    ups = client.get("/api/entities?type=ups").get_json()["entities"][0]
    tree = client.get(f"/api/entities/{ups['id']}/dependencies?depth=12").get_json()["tree"]
    assert {"Jellyfin", "Home Assistant", "DNS and ad blocking"} <= tree_names(tree)
    isp = client.get("/api/entities?type=vendor&q=springfield").get_json()["entities"][0]
    assert ">Internet</a>" in client.get(f"/e/{isp['id']}/sheet?tab=supplies").data.decode()
