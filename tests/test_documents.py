"""Documents: Markdown through the sanitizer, [[slug]] links, and attaching
a document to a record."""
from .conftest import make, section


def render(app, text):
    from hyprvolt.core.markdown import render as md
    with app.test_request_context():
        return str(md(text))


def test_markdown_is_rendered_and_sanitized(app, client, h, admin):
    html = render(app, "# Restore\n\nRun `zfs rollback`.\n\n<script>alert(1)</script><img src=x onerror=alert(1)>")
    assert '<h2 id="h-restore" data-level="1">Restore</h2>' in html and "<code>zfs rollback</code>" in html
    assert "<script" not in html and "onerror" not in html


def test_headings_keep_their_levels_and_get_anchors(app, client, h, admin):
    html = render(app, "# Setup\n\n## Install\n\n### Options\n\nSee [install](#h-install).")
    assert '<h2 id="h-setup" data-level="1">' in html and '<h2 id="h-install">' in html and '<h3 id="h-options">' in html
    # Three headings or more: a contents list at the top, linking to each.
    assert html.startswith('<nav class="doc-contents"') and '<a href="#h-options">Options</a>' in html
    # An info button says where it comes from; its id follows the headings, so
    # the same text renders the same (the page editor compares renderings).
    assert 'class="infotip" popovertarget="contents-help-' in html and "Filled in from the headings" in html
    assert render(app, "# Setup\n\n## Install\n\n### Options\n\nOther words.").split("<ol>")[0] == html.split("<ol>")[0]
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
    # Each carries its slug and the record's name, for the page editor to write back.
    assert html.count('data-wiki="pve1" data-name="pve1"') == 2
    assert '<s data-wiki="nowhere" data-name="nowhere">nowhere</s>' in html
    # A deleted record no longer resolves.
    client.post(f"/api/entities/{host['id']}/delete", headers=h)
    assert '<s data-wiki="pve1" data-name="pve1">pve1</s>' in render(app, "[[pve1]]")


def test_markdown_is_rendered_for_the_page_editor(client, h, admin, viewer):
    host = make(client, h, name="Main host", slug="pve1")
    resp = client.post("/api/markdown", json={"text": "# Hi\n\nOn [[pve1]] and [[gone|elsewhere]]."}, headers=h)
    html = resp.get_json()["html"]
    assert '<h2 id="h-hi" data-level="1">Hi</h2>' in html
    assert f'<a href="/e/{host["id"]}" data-wiki="pve1" data-name="Main host"' in html
    assert '<s data-wiki="gone" data-name="gone">elsewhere</s>' in html
    assert client.post("/api/markdown", json={}, headers=h).status_code == 400
    other, oh = viewer
    assert other.post("/api/markdown", json={"text": "x"}, headers=oh).status_code == 403


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


def test_a_document_prints_as_paper(client, h, admin, viewer):
    host = make(client, h, name="pve1")
    doc = make(client, h, "document", name="Restore <the> NAS", status="draft", tags="runbooks",
               **{"f.body": "# Before\n\n## Check\n\n## Stop\n\nOn [[pve1]].\n\n```bash\nzfs list\n```"})
    sheet = client.get(f"/e/{doc['id']}/sheet").data.decode()
    assert f'data-printed="/documents/{doc["id"]}/print"' in sheet
    assert "data-printed" not in client.get(f"/e/{host['id']}/sheet").data.decode()   # only documents

    other, _ = viewer                                       # a viewer may print it
    page = other.get(f"/documents/{doc['id']}/print").data.decode()
    assert "<title>Restore &lt;the&gt; NAS</title>" in page          # the PDF's file name
    assert 'class="printdoc-title">Restore &lt;the&gt; NAS</h1>' in page
    assert ">Draft</dd>" in page and ">runbooks</dd>" in page and f"/e/{doc['id']}</a>" in page
    # Its own contents list, with no info button; the anchors are the page's own.
    assert 'class="printdoc-contents"' in page and "infotip" not in page
    assert f'<a href="#d{doc["id"]}-h-check">Check</a>' in page and f'id="d{doc["id"]}-h-check"' in page
    assert f'href="/e/{host["id"]}"' in page and 'class="hl-' in page
    assert "With its" not in page                           # no pages to take in
    assert client.get(f"/documents/{host['id']}/print").status_code == 404
    assert client.get("/documents/99999/print").status_code == 404


def test_a_manual_prints_whole_with_its_pages(client, h, admin):
    top, (setup, overview, trouble) = manual(client, h)
    deep = make(client, h, "document", name="Logs", **{"f.parent": trouble["id"], "f.body": "Read [[setup]]."})
    one = client.get(f"/documents/{top['id']}/print").data.decode()
    assert "With its 4 pages" in one and ">Setup</h2>" not in one
    whole = client.get(f"/documents/{top['id']}/print?pages=1").data.decode()
    order = [whole.index(f'id="doc-{d["id"]}"') for d in (top, overview, setup, trouble, deep)]
    assert order == sorted(order)
    assert f'<li class="printdoc-toc-page" style="--depth: 2">\n          <a href="#doc-{deep["id"]}">Logs</a>' in whole
    # A link to a page in the same copy leads there.
    assert f'href="#doc-{setup["id"]}"' in whole.split(f'id="doc-{deep["id"]}"')[1]
    # Asked of a page with none under it, the whole is the page alone.
    alone = client.get(f"/documents/{deep['id']}/print?pages=1").data.decode()
    assert "printdoc-contents" not in alone and alone.count('class="printdoc-sheet"') == 1


def test_a_document_downloads_as_a_pdf(app, client, h, admin, viewer):
    import io

    import pypdf

    from .test_images import attach_picture
    top, (setup, overview, trouble) = manual(client, h)
    photo = attach_picture(client, h, top["id"], "rack.jpg", size=(400, 200))
    client.post(f"/api/entities/{top['id']}", headers=h, json={
        "f.body": f"# Rack\n\n![The rack](/attachments/{photo['id']}/rack.jpg)\n\n"
                  "![Elsewhere](http://192.0.2.1/x.png)\n\nSee [[setup]]."})
    sheet = client.get(f"/e/{top['id']}/sheet").data.decode()
    assert f'data-pdf="/documents/{top["id"]}/print.pdf"' in sheet
    page = client.get(f"/documents/{top['id']}/print?pages=1&paper=a4").data.decode()
    assert f'href="/documents/{top["id"]}/print.pdf?pages=1&amp;paper=a4"' in page and "printdoc--a4" in page

    other, _ = viewer
    resp = other.get(f"/documents/{top['id']}/print.pdf?pages=1&paper=a4")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    assert 'attachment; filename="IMS Exporter.pdf"' in resp.headers["Content-Disposition"]
    pdf = pypdf.PdfReader(io.BytesIO(resp.data))
    assert len(pdf.pages) == 4 and round(float(pdf.pages[0].mediabox.width)) == 595          # A4, a page each
    assert pdf.metadata.title == "IMS Exporter"
    assert [o.title for o in pdf.outline if not isinstance(o, list)] == \
        ["IMS Exporter", "Overview", "Setup", "Troubleshooting"]
    assert "/XObject" in pdf.pages[0]["/Resources"]                  # the attached picture
    first = pdf.pages[0].extract_text()
    assert "IMS Exporter" in first and "1 / 4" in first
    # Letter unless A4 is chosen.
    one = pypdf.PdfReader(io.BytesIO(client.get(f"/documents/{setup['id']}/print.pdf").data))
    assert len(one.pages) == 1 and round(float(one.pages[0].mediabox.width)) == 612


def test_the_pdf_loads_only_the_apps_own_files(app):
    import pytest

    from hyprvolt.modules.documents.printed import _local
    with app.test_request_context(base_url="http://hv.local"):
        body, kind = _local("http://hv.local/static/css/app.css?v=1")
        assert b".printdoc" in body and kind == "text/css"
        for url in ("http://192.0.2.1/x.png", "http://hv.local.evil/static/css/app.css",
                    "file:///etc/passwd", "http://hv.local/static/../config.py", "http://hv.local/api/entities",
                    "http://hv.local/attachments/99999/x.png", "data:image/png;base64,AAAA"):
            with pytest.raises(ValueError):
                _local(url)
