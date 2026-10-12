"""Documents: Markdown through the sanitizer, [[slug]] links, and attaching
a document to a record."""
from .conftest import make, section


def render(app, text):
    from hyprvolt.core.markdown import render as md
    with app.test_request_context():
        return str(md(text))


def test_markdown_is_rendered_and_sanitized(app, client, h, admin):
    html = render(app, "# Restore\n\nRun `zfs rollback`.\n\n<script>alert(1)</script><img src=x onerror=alert(1)>")
    assert '<h2 id="h-restore">Restore</h2>' in html and "<code>zfs rollback</code>" in html
    assert "<script" not in html and "onerror" not in html


def test_headings_keep_their_levels_and_get_anchors(app, client, h, admin):
    html = render(app, "# Setup\n\n## Install\n\n### Options\n\nSee [install](#h-install).")
    assert '<h2 id="h-setup">' in html and '<h2 id="h-install">' in html and '<h3 id="h-options">' in html
    # Three headings or more: a contents list at the top, linking to each.
    assert html.startswith('<nav class="doc-contents"') and '<a href="#h-options">Options</a>' in html
    assert '<a href="#h-install">install</a>' in html            # same page: no new tab
    assert "doc-contents" not in render(app, "## Only one")


def test_typed_ids_and_classes_are_refused(app, client, h, admin):
    html = render(app, '<h2 id="csrf">x</h2><h3 id="h-ok">y</h3><code class="banner">z</code>'
                       '<code class="language-sql">w</code><table><tr><td colspan="2" rowspan="x">c</td></tr></table>')
    assert 'id="csrf"' not in html and 'id="h-ok"' in html and "banner" not in html
    assert 'class="language-sql"' in html and 'colspan="2"' in html and "rowspan" not in html


def test_code_is_highlighted_for_its_language(app, client, h, admin):
    html = render(app, '```powershell\nGet-Service -Name "sshd" # check\n```\n\n```madeup\n<b>x</b>\n```')
    assert '<pre data-lang="powershell"><code class="language-powershell">' in html and 'class="hl-' in html
    assert '<pre data-lang="madeup"><code class="language-madeup">&lt;b&gt;x&lt;/b&gt;' in html
    assert "<b>" not in html


def test_task_lists_show_checkboxes(app, client, h, admin):
    html = render(app, "- [ ] back up\n- [x] tested\n- plain")
    assert '<li class="task"><input type="checkbox" disabled aria-label="Not done"> back up' in html
    assert 'checked aria-label="Done"> tested' in html and "<li>plain</li>" in html


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


def manual(client, h):
    top = make(client, h, "document", name="IMS Exporter", **{"f.body": "The front page."})
    pages = [make(client, h, "document", name=n, **{"f.parent": top["id"], "f.position": p, "f.body": n})
             for n, p in (("Setup", 20), ("Overview", 10), ("Troubleshooting", 30))]
    return top, pages


def test_documents_have_pages_in_order(client, h, admin):
    top, (setup, overview, trouble) = manual(client, h)
    sheet = client.get(f"/e/{top['id']}/sheet").data.decode()
    assert sheet.index(">Overview</a>") < sheet.index(">Setup</a>") < sheet.index(">Troubleshooting</a>")
    assert "Add a page" in sheet
    page = client.get(f"/e/{setup['id']}/sheet").data.decode()
    assert 'aria-label="Part of"' in page and ">IMS Exporter</a>" in page
    assert "doc-pager-prev" in page and "Overview</a>" in page.split("doc-pager-prev")[1]
    assert "Troubleshooting" in page.split("doc-pager-next")[1]
    listed = client.get("/documents?f=top&view=list").data.decode()
    assert ">IMS Exporter<" in listed and ">Setup<" not in listed


def test_a_page_cannot_contain_itself(client, h, admin):
    top, (setup, *_ ) = manual(client, h)
    loop = client.post(f"/api/entities/{top['id']}", json={"f.parent": setup["id"]}, headers=h)
    assert loop.status_code == 400 and "page of itself" in loop.get_json()["error"]
    own = client.post(f"/api/entities/{top['id']}", json={"f.parent": top["id"]}, headers=h)
    assert own.status_code == 400


def test_a_document_lists_the_documents_that_link_to_it(client, h, admin):
    target = make(client, h, "document", name="Glossary", slug="glossary")
    make(client, h, "document", name="Setup", **{"f.body": "Terms are in [[glossary]]."})
    make(client, h, "document", name="Unrelated", **{"f.body": "Nothing here, [[glossary-2]] is another."})
    tab = section(client.get(f"/e/{target['id']}/sheet?tab=linked").data.decode(), "linked")
    listed, choices = tab.split('class="pickform"')
    assert ">Setup</a>" in listed and "Unrelated" not in listed
    assert "<span>Unrelated</span>" in choices                    # offered to cross-link
    assert 'data-tab="linked"' in client.get(f"/e/{target['id']}/sheet").data.decode()


def test_documents_are_cross_linked_from_a_list_and_read_from_both_ends(client, h, admin, editor):
    a = make(client, h, "document", name="Network runbook")
    b = make(client, h, "document", name="Firewall rules")
    c = make(client, h, "document", name="VPN setup", **{"f.parent": b["id"]})
    make(client, h, "document", name="Wiki index", **{"f.body": "Start at [[network-runbook]]."})
    hidden = make(client, h, "document", name="Admin notes", access="private")
    tab = section(client.get(f"/e/{a['id']}/sheet").data.decode(), "linked")
    assert "<span>VPN setup · Firewall rules</span>" in tab              # a page says whose
    assert "<span>Network runbook</span>" not in tab                     # not itself

    resp = client.post(f"/documents/{a['id']}/links", json={"ids": f"{b['id']},{c['id']},{hidden['id']}"}, headers=h)
    assert resp.status_code == 200 and resp.get_json()["undo"]["body"] == {"ids": ""}
    tab = section(client.get(f"/e/{a['id']}/sheet").data.decode(), "linked")
    listed = tab.split('class="pickform"')[0]
    assert ">Firewall rules</a>" in listed and ">VPN setup</a>" in listed
    assert listed.index(">Wiki index</a>") > listed.index("Links here in its text")   # mentioned, not cross-linked
    assert 'data-tab="linked"' in client.get(f"/e/{a['id']}/sheet").data.decode()
    # The same link from the other end, and in Relationships as "see also".
    back = client.get(f"/e/{b['id']}/sheet").data.decode()
    assert ">Network runbook</a>" in section(back, "linked") and ">see also<" in section(back, "relationships")

    # Unticked from the other end: gone from both. The one out of the
    # editor's sight is left alone.
    other, oh = editor
    resp = other.post(f"/documents/{a['id']}/links", json={"ids": str(c["id"])}, headers=oh)
    assert resp.status_code == 200
    assert ">Firewall rules</a>" not in section(client.get(f"/e/{a['id']}/sheet").data.decode(), "linked").split('class="pickform"')[0]
    assert ">Admin notes</a>" in section(client.get(f"/e/{a['id']}/sheet").data.decode(), "linked")
    # Undo puts back what was there.
    undo = resp.get_json()["undo"]
    assert other.post(undo["url"], json=undo["body"], headers=oh).status_code == 200
    assert ">Firewall rules</a>" in section(client.get(f"/e/{a['id']}/sheet").data.decode(), "linked")

    assert client.post(f"/documents/{a['id']}/links", json={"ids": "99999"}, headers=h).status_code == 400
    server = make(client, h, "server", name="srv1")
    assert client.post(f"/documents/{server['id']}/links", json={"ids": ""}, headers=h).status_code == 404
    client.post("/admin/users/2/role", json={"role": "viewer"}, headers=h)
    v, vh = editor
    assert v.post(f"/documents/{a['id']}/links", json={"ids": ""}, headers=vh).status_code == 403
    assert 'class="pickform"' not in v.get(f"/e/{a['id']}/sheet").data.decode()


def test_a_markdown_field_offers_every_document_to_link(client, h, admin, viewer):
    manual = make(client, h, "document", name="Manual", slug="manual")
    make(client, h, "document", name="Install", slug="install", **{"f.parent": manual["id"]})
    make(client, h, "document", name="Admin notes", slug="admin-notes", access="private")
    found = client.get(f"/documents/choices?exclude={manual['id']}").get_json()["documents"]
    assert [(d["name"], d["slug"], d["parent"]) for d in found] == [("Admin notes", "admin-notes", ""),
                                                                    ("Install", "install", "Manual")]
    v, _ = viewer
    assert [d["slug"] for d in v.get("/documents/choices").get_json()["documents"]] == ["install", "manual"]
    sheet = client.get(f"/e/{manual['id']}/sheet").data.decode()
    assert "data-md-links" in sheet and "data-md-link" in sheet
