"""Printable asset labels for the records of a list, with QR codes."""
from .conftest import make


def test_labels_are_made_for_what_a_list_shows(client, h, admin):
    site = make(client, h, "site", name="Home")
    make(client, h, "server", name="srv1", location_id=site["id"], **{"f.asset_tag": "HV-0042", "f.serial": "SN1"})
    make(client, h, "server", name="srv2", **{"f.serial": "SN2"})
    make(client, h, "nas", name="nas1")
    listing = client.get("/hardware?type=server").data.decode()
    assert "/p/labels/print?type=server&amp;list=hardware" in listing and "Print labels" in listing
    page = client.get("/p/labels/print?type=server&list=hardware").data.decode()
    assert page.count('class="label"') == 2 and ">nas1<" not in page
    assert "Asset tag HV-0042" in page and "Serial SN2" in page and "Home" in page
    assert page.count('class="label-qr"') == 2 and "labels--5160" in page and "data-print" in page
    assert "/hardware?type=server" in page                  # back to the list
    a4 = client.get("/p/labels/print?q=srv1&list=all&size=l7160").data.decode()
    assert a4.count('class="label"') == 1 and "labels--l7160" in a4


def test_a_qr_code_encodes_the_record_link(app):
    from hyprvolt.modules.labels.views import qr
    svg = str(qr("http://localhost/e/12"))
    assert svg.startswith("<svg") and 'class="label-qr"' in svg and "<path" in svg


def test_labels_go_with_their_module(client, h, admin):
    make(client, h, "server", name="srv1")
    client.post("/admin/modules/labels", json={"enabled": False}, headers=h)
    assert client.get("/p/labels/print?list=all").status_code == 404
    assert 'href="/p/labels/print' not in client.get("/hardware").data.decode()
    assert client.get("/p/labels/print?list=nothing").status_code == 404


def _png(color=(0, 0, 0, 255), size=(2400, 800)):
    import io

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, "PNG")
    out.seek(0)
    return out


def test_an_asset_tag_carries_the_equipment_and_the_organization(client, h, admin):
    site = make(client, h, "site", name="Home")
    rack = make(client, h, "room", name="Server room", location_id=site["id"])
    srv = make(client, h, "server", name="srv1", location_id=rack["id"],
               **{"f.asset_tag": "HV-0042", "f.serial": "8XK2LM3", "f.manufacturer": "Dell",
                  "f.model": "PowerEdge R740", "s.addresses.list": "10.0.20.11"})
    page = client.get(f"/p/labels/print?id={srv['id']}").data.decode()
    assert 'Mgmt IP <span class="tag-serial">10.0.20.11</span>' in page
    assert "labels--4x1" in page and page.count('class="label tag"') == 1
    assert '<span class="tag-id">HV-0042</span>' in page and ">srv1<" in page
    assert "Dell PowerEdge R740" in page and ">8XK2LM3<" in page and "Home › Server room" in page
    assert "tag-owner" not in page and 'class="tag-logo"' not in page and "logo in Settings > Asset labels" in page
    assert f'href="/e/{srv["id"]}"' in page and "Back to the record" in page
    assert f"/labels/print.pdf?id={srv['id']}&amp;size=4x1" in page

    assert client.post("/labels/brand", json={"owner": "  Acme   Corp "}, headers=h).get_json() == {"ok": True}
    assert client.post("/labels/brand", json={"owner": "x" * 81}, headers=h).status_code == 400
    resp = client.post("/labels/logo", data={"file": (_png(), "logo.png")}, headers=h,
                       content_type="multipart/form-data")
    assert resp.get_json() == {"ok": True}
    page = client.get(f"/p/labels/print?id={srv['id']}").data.decode()
    assert "Property of Acme Corp" in page and 'class="tag-logo" src="/labels/logo?v=' in page
    assert "in Settings > Asset labels" not in page
    # The logo is kept small enough, as a PNG, and runs nothing on its own.
    logo = client.get("/labels/logo")
    assert logo.mimetype == "image/png" and "sandbox" in logo.headers["Content-Security-Policy"]
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(logo.data)).size == (1200, 400)
    # Only on the asset tag: a sheet of Avery labels stays as it was.
    sheet = client.get("/p/labels/print?list=hardware").data.decode()
    assert "labels--5160" in sheet and "Mgmt IP" not in sheet and "tag-owner" not in sheet and 'class="tag-logo"' not in sheet


def test_a_server_running_a_hypervisor_is_tagged_with_the_hypervisors_management_ip(client, h, admin):
    srv = make(client, h, "server", name="vmsvr1", **{"f.asset_tag": "HV-0007", "s.hypervisor.on": True,
                                                      "s.hypervisor.platform": "vmware",
                                                      "s.hypervisor.address": "172.16.128.20"})
    page = client.get(f"/p/labels/print?id={srv['id']}").data.decode()
    assert 'Mgmt IP <span class="tag-serial">172.16.128.20</span>' in page
    # Its own addresses (an iDRAC) come second to the hypervisor's.
    resp = client.post(f"/api/entities/{srv['id']}", json={"s.addresses.list": "10.0.20.11"}, headers=h)
    assert resp.status_code == 200
    page = client.get(f"/p/labels/print?id={srv['id']}").data.decode()
    assert "172.16.128.20" in page and "10.0.20.11" not in page


def test_a_record_with_no_asset_tag_is_tagged_by_its_name(client, h, admin):
    nas = make(client, h, "nas", name="nas1", **{"f.serial": "SN9"})
    page = client.get(f"/p/labels/print?id={nas['id']}").data.decode()
    assert '<span class="tag-id">nas1</span>' in page and "tag-name" not in page and ">SN9<" in page
    assert "Mgmt IP" not in page


def test_asset_tags_download_as_a_pdf_one_tag_a_page(client, h, admin):
    import io

    import pypdf
    client.post("/labels/brand", json={"owner": "Acme Corp"}, headers=h)
    client.post("/labels/logo", data={"file": (_png(), "logo.png")}, headers=h, content_type="multipart/form-data")
    for n in (1, 2, 3):
        make(client, h, "server", name=f"srv{n}", **{"f.asset_tag": f"HV-000{n}"})
    resp = client.get("/labels/print.pdf?list=hardware&type=server&size=4x1")
    assert resp.mimetype == "application/pdf"
    assert 'filename="Asset tags for servers.pdf"' in resp.headers["Content-Disposition"]
    pdf = pypdf.PdfReader(io.BytesIO(resp.data))
    assert len(pdf.pages) == 3
    box = pdf.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (288, 72)     # 4 × 1 in
    text = pdf.pages[0].extract_text()
    assert "HV-000" in text and "PROPERTY OF ACME CORP" in text.upper()
    assert "/XObject" in pdf.pages[0]["/Resources"]                             # the logo
    # Sheets of Avery labels download too.
    sheet = pypdf.PdfReader(io.BytesIO(client.get("/labels/print.pdf?list=hardware").data))
    assert len(sheet.pages) == 1 and round(float(sheet.pages[0].mediabox.width)) == 612
    assert client.get("/labels/print.pdf?list=hardware&q=nothing-like-it").status_code == 404


def test_a_hardware_record_offers_its_asset_tag(client, h, admin):
    srv = make(client, h, "server", name="srv1")
    vm = make(client, h, "vm", name="vm1")
    sheet = client.get(f"/e/{srv['id']}/sheet").data.decode()
    assert f'href="/p/labels/print?id={srv["id"]}&amp;size=4x1"' in sheet and 'title="Print asset tag"' in sheet
    assert "Print asset tag" not in client.get(f"/e/{vm['id']}/sheet").data.decode()
    client.post("/admin/modules/labels", json={"enabled": False}, headers=h)
    assert "Print asset tag" not in client.get(f"/e/{srv['id']}/sheet").data.decode()


def test_only_an_admin_brands_the_tags_and_logos_are_pictures(client, h, admin, viewer):
    other, oh = viewer
    assert other.post("/labels/brand", json={"owner": "Evil"}, headers=oh).status_code == 403
    assert other.post("/labels/logo", data={"file": (_png(), "l.png")}, headers=oh,
                      content_type="multipart/form-data").status_code == 403
    assert other.get("/labels/logo").status_code == 404
    import io
    for data, name in ((b"not a picture", "x.png"), (b"<?xml version='1.0'?><html/>", "x.svg"),
                       (b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>', "x.svg")):
        resp = client.post("/labels/logo", data={"file": (io.BytesIO(data), name)}, headers=h,
                           content_type="multipart/form-data")
        assert resp.status_code == 400 and resp.get_json()["error"]
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
    assert client.post("/labels/logo", data={"file": (io.BytesIO(svg), "logo.svg")}, headers=h,
                       content_type="multipart/form-data").status_code == 200
    assert other.get("/labels/logo").data == svg
    assert client.post("/labels/logo/remove", headers=h).status_code == 200
    assert client.get("/labels/logo").status_code == 404


def test_a_tag_for_a_hidden_record_is_not_printed(client, h, admin, viewer):
    other, _ = viewer
    assert other.get("/p/labels/print?id=999").status_code == 404
    assert other.get("/p/labels/print?id=abc").status_code == 404
    assert other.get("/labels/print.pdf?id=999").status_code == 404
