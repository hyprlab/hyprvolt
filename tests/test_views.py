"""The pages and fragments the interface is built from: lists, the sheet and
its tabs, the form, and the dashboard."""
import io
import re

from .conftest import make


def test_the_dashboard_counts_modules_and_shows_recent_changes(client, h, admin):
    empty = client.get("/").data.decode()
    assert "Nothing documented yet" in empty
    make(client, h, name="Blue box")
    body = client.get("/").data.decode()
    assert "Recently changed" in body and "Blue box" in body and 'class="tile-num">1<' in body


def test_a_module_list_and_its_sidebar(client, h, admin):
    make(client, h, name="Blue box", tags="lab", **{"f.color": "blue"})
    body = client.get("/example?view=list").data.decode()
    assert "Blue box" in body and "blue" in body            # the list field shows in the row
    assert 'href="/example?tag=lab"' in body                 # tags filter within the module
    assert client.get("/nosuchmodule").status_code == 404


def test_the_new_record_window_offers_every_enabled_module_on_every_page(client, h, admin):
    def offered(url):
        page = client.get(url).data.decode()
        kinds = page.split('id="newrec-list"')[1].split('id="newrec-none"')[0]
        return set(re.findall(r'data-kind-type="([a-z_]+)"', kinds))
    everything = offered("/")
    assert {"server", "vm", "subnet", "vendor", "document"} <= everything
    for url in ("/network", "/hardware?view=list", "/contacts"):
        assert offered(url) == everything, url
    page = client.get("/").data.decode()
    assert 'id="new-btn" data-new-record' in page and 'id="new-menu"' not in page
    # The kinds a type comes in are found too, and start its form with the kind chosen.
    assert 'data-kind-type="network_device" data-kind="switch" data-label="Switch" data-text="switch"' in page
    assert 'data-kind-type="service" data-kind="dns" data-label="DNS" data-text="DNS"' in page
    assert 'data-kind="other"' not in page
    client.post("/admin/modules/contacts", json={"enabled": False}, headers=h)
    assert "vendor" not in offered("/network")


def test_the_sheet_has_the_core_sections_one_after_another(client, h, admin):
    g = make(client, h, name="Blue box", **{"f.color": "blue"}, notes="Under **the** desk.")
    body = client.get(f"/e/{g['id']}/sheet").data.decode()
    links = [part.split('data-tab="')[1].split('"')[0] for part in body.split('<a href="#section-')[1:]]
    order = ["overview", "relationships", "documents", "secrets", "attachments", "history", "changes"]
    assert links == order
    # Every section is on the page, in the rail's order.
    sections = [part.split('"')[0] for part in body.split('data-panel="')[1:]]
    assert sections == order and body.count('class="sheet-section-title"') == len(order) - 1
    # An editor edits the fields in place; the notes stay formatted.
    assert "<strong>the</strong>" in body and 'name="f.color"' in body and "data-autosave" in body
    # ?tab= names the section to start at, and the rail marks it.
    page = client.get(f"/e/{g['id']}/sheet?tab=history").data.decode()
    assert 'data-tab="history" aria-current="true"' in page and 'data-tab="history"' in page.split('class="sheet-content"')[1][:200]
    # An unknown one falls back to the Overview.
    assert 'data-tab="overview" aria-current="true"' in client.get(f"/e/{g['id']}/sheet?tab=nope").data.decode()


def test_the_documents_tab_lists_attached_and_mentioning_documents(client, h, admin):
    g = make(client, h, name="Blue box")
    make(client, h, "document", name="Box manual", attach_to=g["id"])
    make(client, h, "document", name="Shelf plan", **{"f.body": "The [[blue-box]] goes on top."})
    body = client.get(f"/e/{g['id']}/sheet?tab=documents").data.decode()
    assert "Box manual" in body and "Mentioned in" in body and "Shelf plan" in body


def test_the_form_follows_the_schema(client, h, admin):
    client.post("/api/custom-fields", json={"entity_type": "gadget", "label": "Owner", "kind": "select",
                                            "options": "Ops,Dev"}, headers=h)
    body = client.get("/e/form?type=gadget").data.decode()
    assert 'name="f.color"' in body and 'name="c.owner"' in body and "<option value=\"Ops\"" in body
    assert 'data-title="New gadget"' in body
    g = make(client, h, name="Blue box", **{"f.color": "blue"})
    edit = client.get(f"/e/{g['id']}/form").data.decode()
    assert 'value="Blue box"' in edit and 'value="blue"' in edit
    assert client.get("/e/form?type=nothing").status_code == 404


def test_a_new_records_form_comes_in_steps(client, h, admin):
    body = client.get("/e/form?type=server&f.kind=tower").data.decode()
    steps = re.findall(r'data-step="([^"]*)"', body)
    assert steps[:4] == ["Basics", "", "Specs", "Purchase"] and steps[-1] == "Notes"
    assert 'data-step="Rack position" data-section="rack" hidden' in body
    assert '<option value="tower" selected>' in body
    # The window has the error and Create; an edit's form keeps its own.
    assert 'type="submit"' not in body
    g = make(client, h, name="Blue box")
    assert 'type="submit"' in client.get(f"/e/{g['id']}/form").data.decode()


def test_viewers_get_no_form_and_no_edit_buttons(client, h, admin, viewer):
    g = make(client, h, name="Blue box")
    other, _ = viewer
    assert other.get(f"/e/{g['id']}/form").status_code == 403
    assert other.get("/e/form?type=gadget").status_code == 403
    page = other.get("/example").data.decode()
    assert 'id="sheet-edit"' not in page and 'id="sheet-delete"' not in page and "data-new-type" not in page
    assert 'id="entity-modal"' not in page
    sheet = other.get(f"/e/{g['id']}/sheet?tab=relationships").data.decode()
    assert "linkform" not in sheet


def test_the_link_form_waits_behind_add_link(client, h, admin):
    g = make(client, h, name="Blue box")
    sheet = client.get(f"/e/{g['id']}/sheet?tab=relationships").data.decode()
    assert f'data-show="linkform-{g["id"]}"' in sheet and f'id="linkform-{g["id"]}" hidden' in sheet
    # The record is found by typing in the field, not in the search window.
    assert f'<input type="text" data-pick data-pick-into="other_id" data-pick-exclude="{g["id"]}"' in sheet
    assert "pickbtn" not in sheet


def test_a_deleted_record_shows_how_to_get_it_back(client, h, admin):
    g = make(client, h, name="Blue box")
    client.post(f"/api/entities/{g['id']}/delete", headers=h)
    body = client.get(f"/e/{g['id']}/sheet").data.decode()
    assert "Deleted" in body and f"/api/entities/{g['id']}/restore" in body
    listed = client.get("/all?deleted=1&view=list").data.decode()
    assert "Blue box" in listed and "Recently deleted" in listed


def test_entity_links_redirect_to_their_module(client, h, admin):
    g = make(client, h, name="Blue box")
    resp = client.get(f"/e/{g['id']}")
    assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/example?open={g['id']}")


def test_history_tab_reads_as_sentences(client, h, admin):
    g = make(client, h, name="Box", **{"f.color": "red"})
    client.post(f"/api/entities/{g['id']}", json={"f.color": "green"}, headers=h)
    client.post(f"/api/entities/{g['id']}/attachments", headers=h, content_type="multipart/form-data",
                data={"file": (io.BytesIO(b"x"), "photo.png", "image/png")})
    body = client.get(f"/e/{g['id']}/sheet?tab=history").data.decode()
    assert "Ada</strong> edited" in body and "<del>red</del>" in body and "<ins>green</ins>" in body
    assert "photo.png" in body


def test_user_text_is_escaped_everywhere(client, h, admin):
    g = make(client, h, name="<script>alert(1)</script>", tags="<b>x</b>", **{"f.color": "<i>c</i>"})
    for url in ("/example", "/example?view=list", "/", f"/e/{g['id']}/sheet", f"/e/{g['id']}/form",
                f"/e/{g['id']}/sheet?tab=history"):
        body = client.get(url).data.decode()
        assert "<script>alert" not in body and "<b>x</b>" not in body and "<i>c</i>" not in body, url


def test_an_account_can_see_one_section_at_a_time(client, h, admin):
    g = make(client, h, name="Blue box")
    page = client.get("/").get_data(as_text=True)
    assert 'id="record-scroll" checked' in page
    assert client.post("/settings", json={"record_scroll": False}, headers=h).status_code == 200
    body = client.get(f"/e/{g['id']}/sheet?tab=history").data.decode()
    assert 'data-scroll="0"' in body and body.count('data-panel="') == 1 and 'data-panel="history"' in body
    assert body.count('<a href="#section-') == 7                  # the rail still lists them all
    assert 'id="record-scroll" >' in client.get("/").get_data(as_text=True)
    client.post("/settings", json={"record_scroll": True}, headers=h)
    assert client.get(f"/e/{g['id']}/sheet").data.decode().count('data-panel="') == 7


def test_help_explains_links_and_cables_from_the_registry(client, h, admin):
    page = client.get("/").data.decode()
    assert 'id="help-modal"' in page and 'data-open="help-modal"' in page
    assert 'data-pane="versus"' in page and "Do I link what is cabled?" in page
    # The kinds of link come from the core and the modules turned on, with which carry a dependency.
    assert "<tr><td>runs on</td><td>runs</td><td>Yes</td></tr>" in page
    assert "<tr><td>is carried by</td><td>carries</td><td>Yes</td></tr>" in page
