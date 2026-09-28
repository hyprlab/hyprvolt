"""Editing a record where it is shown: an editor's Overview is its form,
each field saved on its own; a viewer's reads as a page."""
from .conftest import make


def sheet(client, entity_id, tab="overview"):
    return client.get(f"/e/{entity_id}/sheet?tab={tab}").get_data(as_text=True)


def test_an_editor_edits_the_overview_and_a_viewer_reads_it(client, h, admin, viewer):
    g = make(client, h, name="Blue box", tags="lab", notes="Under **the** desk.", **{"f.color": "blue"})
    html = sheet(client, g["id"])
    assert f'data-autosave="/api/entities/{g["id"]}"' in html
    for control in ('name="name"', 'name="status"', 'name="tags"', 'name="slug"', 'name="f.color"', 'name="notes"'):
        assert control in html and "data-save" in html, control
    assert 'value="lab"' in html and "<strong>the</strong>" in html      # notes stay formatted until Edit
    them, _ = viewer
    page = sheet(them, g["id"])
    assert "data-autosave" not in page and "data-save" not in page and 'name="f.color"' not in page
    assert '<h1 class="sheet-title" data-live="title">Blue box</h1>' in page and ">lab</a>" in page


def test_a_field_saves_on_its_own(client, h, admin):
    g = make(client, h, name="Blue box", tags="lab", **{"f.color": "blue"})
    resp = client.post(f"/api/entities/{g['id']}", json={"f.color": "green"}, headers=h)
    got = resp.get_json()["entity"]
    assert got["fields"]["color"] == "green" and got["tags"] == ["lab"] and got["name"] == "Blue box"
    bad = client.post(f"/api/entities/{g['id']}", json={"name": ""}, headers=h)
    assert bad.status_code == 400 and bad.get_json()["error"] == "Give it a name."


def test_a_deleted_record_is_restored_before_it_is_edited(client, h, admin):
    g = make(client, h, name="Blue box")
    client.post(f"/api/entities/{g['id']}/delete", headers=h)
    assert "data-autosave" not in sheet(client, g["id"])


def test_other_modules_sections_and_long_text_are_edited_in_place(client, h, admin):
    srv = make(client, h, "server", name="pve1")
    html = sheet(client, srv["id"])
    assert "data-save-group" in html and 'name="s.rack.rack_id"' in html
    assert '<option value="nas" >NAS</option>' in html and "data-retype" in html
    doc = make(client, h, "document", name="Runbook", **{"f.body": "# Steps\n\nReboot it."})
    html = sheet(client, doc["id"])
    assert 'data-prose' in html and 'name="f.body"' in html and '<h2 id="h-steps">' in html and ">Edit</button>" in html
    assert 'name="access"' in html


def test_a_card_is_drawn_on_its_own_for_the_list(client, h, admin):
    g = make(client, h, name="Blue box")
    card = client.get(f"/e/{g['id']}/card").get_data(as_text=True)
    assert f'data-item="{g["id"]}"' in card and 'class="card' in card
    row = client.get(f"/e/{g['id']}/card?view=list").get_data(as_text=True)
    assert 'class="row' in row and "Blue box" in row
