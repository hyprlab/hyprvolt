"""Settings > Tags: renaming a tag on every record, merging two, removing
one, each with Undo, and who may."""
from .conftest import make


def tag_id(client, name):
    page = client.get("/").get_data(as_text=True)
    pane = page.split('id="settings-tags"')[1].split("</section>")[0]
    return int(pane.split(f'value="{name}"')[0].rsplit("/api/tags/", 1)[1].split("/", 1)[0])


def tags_of(client, entity):
    return client.get(f"/api/entities/{entity['id']}").get_json()["entity"]["tags"]


def counts(client):
    return {t["name"]: t["count"] for t in client.get("/api/tags").get_json()["tags"]}


def test_the_pane_lists_every_tag_with_its_count(client, h, admin):
    make(client, h, name="A", tags="prod, lab")
    make(client, h, name="B", tags="prod")
    pane = client.get("/").get_data(as_text=True).split('id="settings-tags"')[1].split("</section>")[0]
    assert pane.index('value="lab"') < pane.index('value="prod"')
    assert "2 records" in pane and "1 record<" in pane


def test_a_rename_reaches_every_record_and_search_and_undoes(client, h, admin):
    a = make(client, h, name="A", tags="prod, lab")
    b = make(client, h, name="B", tags="prod")
    resp = client.post(f"/api/tags/{tag_id(client, 'prod')}/rename", json={"name": " Production "}, headers=h).get_json()
    assert resp["message"] == "Renamed to Production"
    assert tags_of(client, a) == ["lab", "Production"] and tags_of(client, b) == ["Production"]
    assert len(client.get("/api/entities?q=production").get_json()["entities"]) == 2
    client.post(resp["undo"]["url"], json=resp["undo"]["body"], headers=h)
    assert counts(client) == {"lab": 1, "prod": 2}


def test_only_the_case_changes(client, h, admin):
    a = make(client, h, name="A", tags="prod")
    resp = client.post(f"/api/tags/{tag_id(client, 'prod')}/rename", json={"name": "Prod"}, headers=h).get_json()
    assert resp["message"] == "Renamed to Prod" and tags_of(client, a) == ["Prod"]


def test_the_name_of_another_tag_merges_them_and_undo_parts_them(client, h, admin):
    a = make(client, h, name="A", tags="prod, production")
    b = make(client, h, name="B", tags="prod")
    c = make(client, h, name="C", tags="production")
    resp = client.post(f"/api/tags/{tag_id(client, 'prod')}/rename", json={"name": "PRODUCTION"}, headers=h).get_json()
    assert resp["message"] == "Merged into production"
    assert counts(client) == {"production": 3}
    assert tags_of(client, a) == ["production"] and tags_of(client, b) == ["production"]
    assert client.post(resp["undo"]["url"], json=resp["undo"]["body"], headers=h).status_code == 200
    assert tags_of(client, a) == ["prod", "production"] and tags_of(client, b) == ["prod"]
    assert tags_of(client, c) == ["production"]


def test_removing_a_tag_takes_it_off_every_record_and_undoes(client, h, admin):
    a = make(client, h, name="A", tags="prod, lab")
    b = make(client, h, name="B", tags="prod")
    gone = make(client, h, name="Gone", tags="prod")
    client.post(f"/api/entities/{gone['id']}/delete", headers=h)
    resp = client.post(f"/api/tags/{tag_id(client, 'prod')}/delete", headers=h).get_json()
    assert resp["message"] == "prod removed from 2 records"
    assert counts(client) == {"lab": 1} and tags_of(client, b) == []
    assert client.get("/api/entities?q=prod").get_json()["entities"] == []
    client.post(resp["undo"]["url"], json=resp["undo"]["body"], headers=h)
    assert tags_of(client, a) == ["lab", "prod"] and tags_of(client, b) == ["prod"]


def test_a_name_is_needed(client, h, admin):
    make(client, h, name="A", tags="prod")
    resp = client.post(f"/api/tags/{tag_id(client, 'prod')}/rename", json={"name": "  "}, headers=h)
    assert resp.status_code == 400 and resp.get_json()["error"] == "Give the tag a name."


def test_only_admins_edit_tags(client, h, admin, editor):
    make(client, h, name="A", tags="prod")
    other, oh = editor
    tid = tag_id(client, "prod")
    assert other.post(f"/api/tags/{tid}/rename", json={"name": "x"}, headers=oh).status_code == 403
    assert other.post(f"/api/tags/{tid}/delete", headers=oh).status_code == 403
    assert 'id="settings-tags"' not in other.get("/").get_data(as_text=True)
