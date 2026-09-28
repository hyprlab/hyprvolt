"""Restricted documents: hidden from anyone below their level everywhere a
record can show up, as if they were not there."""
import io

from .conftest import make

SECRET_WORD = "zebrafish"


def setup_docs(client, h):
    server = make(client, h, "server", name="srv1")
    open_doc = make(client, h, "document", name="Open manual", slug="open-manual",
                    **{"f.body": "See [[private-manual]] and [[editors-manual]]."})
    private = make(client, h, "document", name="Private manual", slug="private-manual", access="private",
                   tags="manuals", **{"f.body": f"The {SECRET_WORD} procedure.", "f.parent": open_doc["id"]})
    editors = make(client, h, "document", name="Editors manual", slug="editors-manual", access="editors",
                   **{"f.body": "For editors [[open-manual]]."})
    client.post("/api/relationships", json={"kind": "documented_by", "source_id": server["id"],
                                            "target_id": private["id"]}, headers=h)
    client.post(f"/api/entities/{private['id']}/attachments", headers=h, content_type="multipart/form-data",
                data={"file": (io.BytesIO(b"hello"), "notes.txt")})
    return server, open_doc, private, editors


def seen(c, url):
    resp = c.get(url)
    return resp.status_code, resp.data.decode()


def test_a_private_document_is_hidden_from_a_viewer_everywhere(client, h, admin, viewer):
    server, open_doc, private, editors = setup_docs(client, h)
    att = client.get(f"/api/entities/{private['id']}/attachments").get_json()["attachments"][0]
    other, oh = viewer
    for url in (f"/api/entities/{private['id']}", f"/e/{private['id']}/sheet", f"/e/{private['id']}",
                "/api/entities/by-slug/private-manual", f"/api/entities/{private['id']}/history",
                f"/api/entities/{private['id']}/attachments", f"/attachments/{att['id']}",
                f"/api/entities/{private['id']}/relationships", f"/api/entities/{editors['id']}"):
        assert other.get(url).status_code == 404, url
    for url in ("/api/entities?limit=500", "/api/entities?slug=private-manual", "/api/entities?q=" + SECRET_WORD,
                "/documents?view=list", "/all?view=list", "/search?q=manual", "/search?q=" + SECRET_WORD,
                "/export/documents.csv", "/api/tags", "/", f"/e/{server['id']}/sheet?tab=documents",
                f"/e/{server['id']}/sheet?tab=relationships", f"/e/{open_doc['id']}/sheet",
                f"/e/{open_doc['id']}/sheet?tab=linked", "/p/labels/print?list=all"):
        status, body = seen(other, url)
        assert status == 200, url
        assert "Private manual" not in body and "Editors manual" not in body and SECRET_WORD not in body, url
    assert '"manuals"' not in other.get("/api/tags").data.decode()
    # The server's history doesn't name the private manual it was linked to.
    for url in (f"/e/{server['id']}/sheet?tab=history", f"/api/entities/{server['id']}/history"):
        assert "Private manual" not in other.get(url).data.decode(), url
    assert "Private manual" in client.get(f"/api/entities/{server['id']}/history").data.decode()
    # A page's field pointing at a private parent reads as restricted.
    page = make(client, h, "document", name="Loose page", **{"f.parent": private["id"]})
    client.post(f"/api/entities/{page['id']}", json={"f.parent": None}, headers=h)
    lines = other.get(f"/api/entities/{page['id']}/history").get_json()["history"]
    assert "Private manual" not in str(lines) and "a restricted record" in str(lines)
    # The link in the open document is struck through, as for a record that isn't there.
    assert "<s>private-manual</s>" in other.get(f"/e/{open_doc['id']}/sheet").data.decode()
    # Its slug can't be taken over or probed by name.
    taken = other.post("/api/entities/by-slug/private-manual", json={"type": "document", "name": "x"}, headers=oh)
    assert taken.status_code == 403                       # a viewer writes nothing
    client.post("/admin/users/2/role", json={"role": "editor"}, headers=h)
    taken = other.post("/api/entities/by-slug/private-manual", json={"type": "document", "name": "x"}, headers=oh)
    assert taken.status_code == 409 and "Private manual" not in taken.get_json()["error"]
    clash = other.post("/api/entities", json={"type": "document", "name": "x", "slug": "private-manual"}, headers=oh)
    assert clash.status_code == 400 and "Private manual" not in clash.get_json()["error"]


def test_levels_follow_the_role_and_the_secrets_permission(client, h, admin, viewer):
    server, open_doc, private, editors = setup_docs(client, h)
    other, oh = viewer
    assert other.get(f"/api/entities/{editors['id']}").status_code == 404
    client.post("/admin/users/2/role", json={"role": "editor"}, headers=h)
    assert other.get(f"/api/entities/{editors['id']}").status_code == 200
    assert other.get(f"/api/entities/{private['id']}").status_code == 404
    # An editor can't make a document private without access to secrets: it would hide it from them.
    refused = other.post(f"/api/entities/{open_doc['id']}", json={"access": "private"}, headers=oh)
    assert refused.status_code == 400 and "hide it from you" in refused.get_json()["error"]
    form = other.get(f"/e/{open_doc['id']}/form").data.decode()
    assert 'value="editors"' in form and 'value="private"' not in form
    client.post("/admin/users/2/secrets", json={"allowed": True}, headers=h)
    assert other.get(f"/api/entities/{private['id']}").status_code == 200
    assert "Private manual" in other.get("/documents?view=list").data.decode()


def test_only_documents_can_be_restricted(client, h, admin):
    server = make(client, h, "server", name="srv1")
    resp = client.post(f"/api/entities/{server['id']}", json={"access": "private"}, headers=h)
    assert resp.status_code == 400 and "only documents" in resp.get_json()["error"]
    doc = make(client, h, "document", name="Manual")
    client.post(f"/api/entities/{doc['id']}", json={"access": "editors"}, headers=h)
    sheet = client.get(f"/e/{doc['id']}/sheet").data.decode()
    assert "Editors only" in sheet and "Editors and admins" in sheet
    changes = client.get(f"/api/entities/{doc['id']}/history").get_json()["history"][0]["changes"]
    assert changes == [{"field": "access", "label": "Visible to", "old": "Everyone", "new": "Editors and admins"}]
