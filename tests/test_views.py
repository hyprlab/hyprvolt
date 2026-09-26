"""The pages and fragments the interface is built from: lists, the sheet and
its tabs, the form, and the dashboard."""
import io

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


def test_the_sheet_has_the_core_tabs(client, h, admin):
    g = make(client, h, name="Blue box", **{"f.color": "blue"}, notes="Under **the** desk.")
    body = client.get(f"/e/{g['id']}/sheet").data.decode()
    tabs = [part.split('"')[0] for part in body.split('role="tab" data-tab="')[1:]]
    assert tabs == ["overview", "relationships", "documents", "secrets", "attachments", "history"]
    assert "<strong>the</strong>" in body and ">blue<" in body
    for tab in ("relationships", "documents", "attachments", "history"):
        resp = client.get(f"/e/{g['id']}/sheet?tab={tab}")
        assert resp.status_code == 200 and f'data-panel="{tab}"' in resp.data.decode()
    # An unknown tab falls back to the Overview.
    assert 'data-panel="overview"' in client.get(f"/e/{g['id']}/sheet?tab=nope").data.decode()


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


def test_viewers_get_no_form_and_no_edit_buttons(client, h, admin, viewer):
    g = make(client, h, name="Blue box")
    other, _ = viewer
    assert other.get(f"/e/{g['id']}/form").status_code == 403
    assert other.get("/e/form?type=gadget").status_code == 403
    page = other.get("/example").data.decode()
    assert 'id="sheet-edit"' not in page and 'id="sheet-delete"' not in page and "data-new-type" not in page
    sheet = other.get(f"/e/{g['id']}/sheet?tab=relationships").data.decode()
    assert "linkform" not in sheet


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
