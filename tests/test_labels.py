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
    assert "Print labels" not in client.get("/hardware").data.decode()
    assert client.get("/p/labels/print?list=nothing").status_code == 404
