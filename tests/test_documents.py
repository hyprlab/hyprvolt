"""Documents: Markdown through the sanitizer, [[slug]] links, and attaching
a document to a record."""
from .conftest import make


def render(app, text):
    from hyprvolt.core.markdown import render as md
    with app.test_request_context():
        return str(md(text))


def test_markdown_is_rendered_and_sanitized(app, client, h, admin):
    html = render(app, "# Restore\n\nRun `zfs rollback`.\n\n<script>alert(1)</script><img src=x onerror=alert(1)>")
    assert "<h3>Restore</h3>" in html and "<code>zfs rollback</code>" in html
    assert "<script" not in html and "onerror" not in html


def test_slug_links_resolve_to_records(app, client, h, admin):
    host = make(client, h, name="pve1")
    html = render(app, "Runs on [[pve1]], see [[pve1|the host]]. Also [[nowhere]].")
    assert f'href="/e/{host["id"]}"' in html and ">pve1</a>" in html and ">the host</a>" in html
    assert "<s>nowhere</s>" in html
    # A deleted record no longer resolves.
    client.post(f"/api/entities/{host['id']}/delete", headers=h)
    assert "<s>pve1</s>" in render(app, "[[pve1]]")


def test_link_labels_cannot_inject_markup(app, client, h, admin):
    make(client, h, name="pve1")
    html = render(app, '[[pve1|<b onclick="x">bold</b>]]')
    assert "<b" not in html and "&lt;b onclick" in html


def test_documents_are_records_and_searchable(client, h, admin):
    doc = make(client, h, "document", name="Restore runbook", **{"f.body": "Use the zpool named tank."})
    assert doc["module"] == "documents" and doc["status"] == "current"
    hits = client.get("/api/entities?q=zpool").get_json()["entities"]
    assert [e["id"] for e in hits] == [doc["id"]]


def test_a_new_document_can_be_attached_to_a_record(client, h, admin):
    host = make(client, h, name="pve1")
    doc = make(client, h, "document", name="pve1 notes", attach_to=host["id"])
    rels = client.get(f"/api/entities/{host['id']}/relationships").get_json()["relationships"]
    assert [(r["label"], r["other"]["id"]) for r in rels] == [("documented by", doc["id"])]


def test_the_knowledge_base_cannot_be_turned_off(app):
    from hyprvolt.models import set_setting
    from hyprvolt.registry import EXTENSION
    with app.app_context():
        set_setting("module:documents:enabled", "0")
    with app.test_request_context():
        assert app.extensions[EXTENSION].is_enabled("documents")
