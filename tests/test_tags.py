"""Settings > Tags: adding a tag before any record has it, renaming one on
every record, merging two, removing one, each with Undo, and who may."""
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
    assert other.post("/api/tags", json={"name": "x"}, headers=oh).status_code == 403
    assert 'id="settings-tags"' not in other.get("/").get_data(as_text=True)


def test_a_tag_added_here_is_offered_before_any_record_has_it(client, h, admin):
    resp = client.post("/api/tags", json={"name": " staging "}, headers=h)
    assert resp.status_code == 200 and resp.get_json()["tag"]["name"] == "staging"
    assert counts(client) == {"staging": 0}
    pane = client.get("/").get_data(as_text=True).split('id="settings-tags"')[1].split("</section>")[0]
    assert 'value="staging"' in pane and "No records yet" in pane
    # The sidebar lists only tags in use; the tag stays kept when its last record lets go.
    assert 'sideitem-title">staging<' not in client.get("/").get_data(as_text=True)
    a = make(client, h, name="A", tags="staging")
    assert 'sideitem-title">staging<' in client.get("/").get_data(as_text=True)
    client.post(f"/api/entities/{a['id']}", json={"tags": ""}, headers=h)
    assert counts(client) == {"staging": 0}
    resp = client.post(f"/api/tags/{tag_id(client, 'staging')}/delete", headers=h).get_json()
    assert resp["message"] == "staging removed" and counts(client) == {}
    client.post(resp["undo"]["url"], json=resp["undo"]["body"], headers=h)
    assert counts(client) == {"staging": 0}


def test_a_tag_typed_in_a_record_goes_when_its_last_record_lets_go(client, h, admin):
    a = make(client, h, name="A", tags="tpyo")
    client.post(f"/api/entities/{a['id']}", json={"tags": "typo"}, headers=h)
    assert counts(client) == {"typo": 1}
    assert 'value="tpyo"' not in client.get("/").get_data(as_text=True)


def test_adding_a_tag_that_exists_says_so(client, h, admin):
    make(client, h, name="A", tags="prod")
    resp = client.post("/api/tags", json={"name": "PROD"}, headers=h)
    assert resp.status_code == 400 and resp.get_json()["error"] == "There is a tag named prod already."
    assert client.post("/api/tags", json={"name": ""}, headers=h).get_json()["error"] == "Give the tag a name."
    # One no record has any more is simply kept.
    a = make(client, h, name="B", tags="old")
    client.post(f"/api/entities/{a['id']}", json={"tags": ""}, headers=h)
    assert client.post("/api/tags", json={"name": "Old"}, headers=h).status_code == 200
    assert counts(client) == {"old": 0, "prod": 1}


def test_merging_a_kept_tag_keeps_the_one_it_joins(client, h, admin):
    client.post("/api/tags", json={"name": "staging"}, headers=h)
    a = make(client, h, name="A", tags="stage")
    client.post(f"/api/tags/{tag_id(client, 'staging')}/rename", json={"name": "stage"}, headers=h)
    client.post(f"/api/entities/{a['id']}", json={"tags": ""}, headers=h)
    assert counts(client) == {"stage": 0}
