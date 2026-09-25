"""Fields kept as links, and form sections one module adds to another's
types: both go through the one write path, with history."""
from .conftest import make


def history(client, entity_id):
    return client.get(f"/api/entities/{entity_id}/history").get_json()["history"]


def test_a_field_kept_as_a_link_is_a_relationship(client, h, admin):
    cell = make(client, h, "battery", name="Cell A")
    other = make(client, h, "battery", name="Cell B")
    gadget = make(client, h, "gadget", name="Lamp", **{"f.battery": cell["id"]})
    assert gadget["fields"]["battery"] == cell["id"]
    rels = client.get(f"/api/entities/{gadget['id']}/relationships").get_json()["relationships"]
    assert [(r["kind"], r["other"]["name"], r["outgoing"]) for r in rels] == [("powered_by", "Cell A", True)]
    # The dependency view follows it: the lamp stops when the cell does.
    tree = client.get(f"/api/entities/{cell['id']}/dependencies").get_json()["tree"]
    assert [n["name"] for n in tree] == ["Lamp"]
    # Changing the field moves the link; the lamp's history has one line.
    client.post(f"/api/entities/{gadget['id']}", json={"f.battery": other["id"]}, headers=h)
    rels = client.get(f"/api/entities/{gadget['id']}/relationships").get_json()["relationships"]
    assert [r["other"]["name"] for r in rels] == ["Cell B"]
    edit = history(client, gadget["id"])[0]
    assert edit["action"] == "edited" and edit["changes"] == [
        {"field": "f.battery", "label": "Battery", "old": "Cell A", "new": "Cell B"}]
    assert history(client, cell["id"])[0]["action"] == "unlinked"
    # Unlinking in the Relationships tab empties the field.
    rel_id = rels[0]["id"]
    client.post(f"/api/relationships/{rel_id}/delete", headers=h)
    got = client.get(f"/api/entities/{gadget['id']}").get_json()["entity"]
    assert got["fields"]["battery"] is None


def test_a_link_field_shows_in_lists_forms_and_search(client, h, admin):
    cell = make(client, h, "battery", name="Cell A")
    gadget = make(client, h, "gadget", name="Lamp", **{"f.battery": cell["id"]})
    listed = client.get("/example?type=gadget&view=list").data.decode()
    assert "Cell A" in listed
    form = client.get(f"/e/{gadget['id']}/form").data.decode()
    assert f'<option value="{cell["id"]}" selected>' in form
    found = client.get("/api/entities?q=cell a&type=gadget").get_json()["entities"]
    assert [e["name"] for e in found] == ["Lamp"]
    wrong = client.post("/api/entities", json={"type": "gadget", "name": "x", "f.battery": gadget["id"]},
                        headers=h)
    assert "right type" in wrong.get_json()["error"]


def test_a_form_section_saves_through_the_write_path(client, h, admin):
    form = client.get("/e/form?type=gadget").data.decode()
    assert 'name="s.sticker.text"' in form and ">Sticker</p>" in form
    assert 's.sticker' not in client.get("/e/form?type=battery").data.decode()
    gadget = make(client, h, "gadget", name="Lamp", **{"s.sticker.text": "Fragile"})
    created = history(client, gadget["id"])[0]
    assert created["action"] == "created" and {"field": "sticker", "label": "Sticker", "old": "",
                                                "new": "Fragile"} in created["changes"]
    assert 'value="Fragile"' in client.get(f"/e/{gadget['id']}/form").data.decode()
    # The API takes the nested form as well; a refusal saves nothing.
    bad = client.post(f"/api/entities/{gadget['id']}", json={"name": "Renamed", "sections": {"sticker": {"text": "x" * 41}}},
                      headers=h)
    assert bad.status_code == 400 and "40 characters" in bad.get_json()["error"]
    assert client.get(f"/api/entities/{gadget['id']}").get_json()["entity"]["name"] == "Lamp"
    client.post(f"/api/entities/{gadget['id']}", json={"sections": {"sticker": {"text": ""}}}, headers=h)
    assert history(client, gadget["id"])[0]["changes"] == [
        {"field": "sticker", "label": "Sticker", "old": "Fragile", "new": ""}]
