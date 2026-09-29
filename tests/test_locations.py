"""The Locations module: the hierarchy, breadcrumbs, rack mounts, conflicts,
and its pages."""
from .conftest import make


def place(client, h):
    site = make(client, h, "site", name="Home", **{"f.code": "HOME"})
    building = make(client, h, "building", name="House", location_id=site["id"])
    room = make(client, h, "room", name="Basement", location_id=building["id"])
    rack = make(client, h, "rack", name="Rack A", location_id=room["id"], **{"f.height_u": 12})
    return site, building, room, rack


def mount(client, h, rack, status=200, **body):
    resp = client.post(f"/locations/racks/{rack['id']}/mounts", json={"height_u": 1, "face": "front", **body},
                       headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def test_the_hierarchy_and_breadcrumbs(client, h, admin):
    site, building, room, rack = place(client, h)
    got = client.get(f"/api/entities/{rack['id']}").get_json()["entity"]
    assert [p["name"] for p in got["path"]] == ["Home", "House", "Basement"]
    assert rack["fields"]["height_u"] == 12 and rack["fields"]["numbering"] == "bottom"
    wrong = client.post("/api/entities", json={"type": "rack", "name": "x", "location_id": site["id"]}, headers=h)
    assert "can only be in a room" in wrong.get_json()["error"]
    no = client.post("/api/entities", json={"type": "site", "name": "x", "location_id": site["id"]}, headers=h)
    assert "has no location" in no.get_json()["error"]
    sheet = client.get(f"/e/{rack['id']}/sheet").data.decode()
    assert 'class="crumbs"' in sheet and ">Basement</a>" in sheet


def test_a_location_cannot_end_up_inside_itself(client, h, admin):
    a = make(client, h, "crate", name="Crate A")
    b = make(client, h, "crate", name="Crate B", location_id=a["id"])
    resp = client.post(f"/api/entities/{a['id']}", json={"location_id": b["id"]}, headers=h)
    assert "inside itself" in resp.get_json()["error"]
    # The form doesn't offer the loop either.
    form = client.get(f"/e/{a['id']}/form").data.decode()
    assert f'<option value="{b["id"]}"' not in form


def test_placing_things_in_a_rack(client, h, admin):
    site, building, room, rack = place(client, h)
    shelf = make(client, h, "shelf", name="Shelf", location_id=room["id"])
    got = mount(client, h, rack, entity_id=shelf["id"], position_u=5, height_u=2, face="full")
    assert got["mount"]["name"] == "Shelf" and got["problems"] == []
    # Mounting moves the record into the rack.
    assert client.get(f"/api/entities/{shelf['id']}").get_json()["entity"]["location"]["id"] == rack["id"]
    mount(client, h, rack, label="Patch panel", position_u=12)
    elevation = client.get(f"/locations/racks/{rack['id']}/elevation").get_json()
    assert elevation["rack"]["used_u"] == 3 and elevation["conflicts"] == []
    # Mounting the same record again moves it rather than doubling it.
    mount(client, h, rack, entity_id=shelf["id"], position_u=1, height_u=2, face="front")
    assert [m["position_u"] for m in client.get(f"/locations/racks/{rack['id']}/elevation").get_json()["mounts"]
            if m["entity_id"] == shelf["id"]] == [1]
    history = client.get(f"/api/entities/{shelf['id']}/history").get_json()["history"]
    assert history[0]["action"] == "mounted" and "Rack A, U1–2, front" in history[0]["changes"][0]["new"]


def test_mounts_are_checked(client, h, admin):
    site, building, room, rack = place(client, h)
    assert "between 1 and 12" in mount(client, h, rack, 400, label="x", position_u=13)["error"]
    assert "name what goes there" in mount(client, h, rack, 400, position_u=1)["error"]
    assert "doesn't go in a rack" in mount(client, h, rack, 400, entity_id=room["id"], position_u=1)["error"]
    assert "front, rear" in mount(client, h, rack, 400, label="x", position_u=1, face="side")["error"]


def test_conflicts_are_flagged_not_refused(client, h, admin):
    site, building, room, rack = place(client, h)
    mount(client, h, rack, label="Switch", position_u=4, height_u=2, face="front")
    rear = mount(client, h, rack, label="PDU", position_u=4, face="rear")
    assert rear["problems"] == []                                    # other face: fine
    full = mount(client, h, rack, label="Server", position_u=5, height_u=2, face="full")
    assert full["problems"] == ["overlaps Switch on the front"]
    # Shrinking the rack pushes something out of range.
    mount(client, h, rack, label="Top", position_u=12)
    client.post(f"/api/entities/{rack['id']}", json={"f.height_u": 10}, headers=h)
    conflicts = client.get(f"/locations/racks/{rack['id']}/elevation").get_json()["conflicts"]
    assert any("outside the rack's U1–U10" in p for c in conflicts for p in c["problems"])
    listed = client.get("/locations?f=conflicts&view=list").data.decode()
    assert "Rack A" in listed and "count--alert" in listed
    sheet = client.get(f"/e/{rack['id']}/sheet?tab=elevation").data.decode()
    assert "is-conflict" in sheet and "--lanes: 2" in sheet


def test_taking_something_out_can_be_undone(client, h, admin):
    site, building, room, rack = place(client, h)
    made = mount(client, h, rack, label="Switch", position_u=4)
    undo = client.post(f"/locations/mounts/{made['mount']['id']}/delete", headers=h).get_json()["undo"]
    assert client.get(f"/locations/racks/{rack['id']}/elevation").get_json()["mounts"] == []
    client.post(undo["url"], json=undo["body"], headers=h)
    assert [m["label"] for m in client.get(f"/locations/racks/{rack['id']}/elevation").get_json()["mounts"]] == ["Switch"]


def test_contents_elevation_and_widget_pages(client, h, admin):
    site, building, room, rack = place(client, h)
    make(client, h, "shelf", name="Storage", location_id=room["id"])
    contents = client.get(f"/e/{room['id']}/sheet?tab=contents").data.decode()
    assert "Rack A" in contents and "Storage" in contents and 'data-new-type="rack"' in contents
    mount(client, h, rack, label="Switch", position_u=4)
    elevation = client.get(f"/e/{rack['id']}/sheet?tab=elevation").data.decode()
    assert "Switch" in elevation and "1 of 12 U in use" in elevation and 'data-fill-form="mount-form-' in elevation
    assert "Rack space" in client.get("/").data.decode()


def test_viewers_see_racks_but_cannot_change_them(client, h, admin, viewer):
    site, building, room, rack = place(client, h)
    other, oh = viewer
    assert other.post(f"/locations/racks/{rack['id']}/mounts", json={"label": "x", "position_u": 1},
                      headers=oh).status_code == 403
    assert other.get(f"/locations/racks/{rack['id']}/elevation").status_code == 200
    page = other.get(f"/e/{rack['id']}/sheet?tab=elevation").data.decode()
    assert "mountform" not in page and "button" not in page.split('class="elevation"')[1].split("</div>\n\n")[0]


def test_turning_locations_off_hides_it_and_keeps_the_data(app, client, h, admin):
    site, building, room, rack = place(client, h)
    from hyprvolt.models import set_setting
    with app.app_context():
        set_setting("module:locations:enabled", "0")
    assert client.get("/locations").status_code == 404
    assert client.get(f"/locations/racks/{rack['id']}/elevation").status_code == 404
    assert client.get(f"/api/entities/{rack['id']}").status_code == 404
    assert "Locations" not in client.get("/").data.decode().split('class="sidebar-scroll"')[1].split("</aside>")[0]
    with app.app_context():
        set_setting("module:locations:enabled", "1")
    assert client.get(f"/api/entities/{rack['id']}").get_json()["entity"]["name"] == "Rack A"


def test_the_rack_position_is_part_of_a_rackmount_form(client, h, admin):
    site, building, room, rack = place(client, h)
    form = client.get(f"/e/form?type=shelf&location_id={rack['id']}").data.decode()
    assert 'name="s.rack.rack_id"' in form and f'<option value="{rack["id"]}" selected>' in form
    assert "s.rack" not in client.get("/e/form?type=room").data.decode()
    shelf = make(client, h, "shelf", name="Shelf", location_id=room["id"],
                 **{"s.rack.rack_id": rack["id"], "s.rack.position_u": 3, "s.rack.height_u": 2, "s.rack.face": "full"})
    # In the rack, located in the rack, and one history line says both.
    assert shelf["location"]["id"] == rack["id"]
    mounts = client.get(f"/locations/racks/{rack['id']}/elevation").get_json()["mounts"]
    assert [(m["name"], m["position_u"], m["height_u"], m["face"]) for m in mounts] == [("Shelf", 3, 2, "full")]
    created = client.get(f"/api/entities/{shelf['id']}/history").get_json()["history"][0]
    fields = {c["field"]: c["new"] for c in created["changes"]}
    assert fields["rack"] == "Rack A, U3–4, full depth" and fields["location"] == "Rack A"
    # Moving it in the form; saving without touching it changes nothing.
    client.post(f"/api/entities/{shelf['id']}", json={"s.rack.rack_id": rack["id"], "s.rack.position_u": 7,
                                                      "s.rack.height_u": 2, "s.rack.face": "full"}, headers=h)
    edit = client.get(f"/api/entities/{shelf['id']}/history").get_json()["history"][0]
    assert edit["changes"] == [{"field": "rack", "label": "Rack position", "old": "Rack A, U3–4, full depth",
                                "new": "Rack A, U7–8, full depth"}]
    client.post(f"/api/entities/{shelf['id']}", json={"name": "Shelf", "s.rack.rack_id": rack["id"],
                                                      "s.rack.position_u": 7, "s.rack.height_u": 2,
                                                      "s.rack.face": "full"}, headers=h)
    assert client.get(f"/api/entities/{shelf['id']}/history").get_json()["history"][0] == edit
    form = client.get(f"/e/{shelf['id']}/form").data.decode()
    assert 'name="s.rack.position_u" min="1" max="60" value="7"' in form
    # Clearing the rack takes it out; the rack's history has both.
    client.post(f"/api/entities/{shelf['id']}", json={"s.rack.rack_id": ""}, headers=h)
    assert client.get(f"/locations/racks/{rack['id']}/elevation").get_json()["mounts"] == []
    actions = [r["action"] for r in client.get(f"/api/entities/{rack['id']}/history").get_json()["history"]]
    assert actions[:3] == ["unmounted", "mounted", "mounted"]


def test_a_tower_server_has_no_rack_position_section(client, h, admin):
    tower = make(client, h, "server", name="tower", **{"f.kind": "tower"})
    racked = make(client, h, "server", name="racked", **{"f.kind": "rack"})
    for entity, hidden in ((tower, True), (racked, False)):
        for url in (f"/e/{entity['id']}/form", f"/e/{entity['id']}/sheet"):
            page = client.get(url).data.decode()
            assert ('<div data-section="rack" hidden>' in page) is hidden, url
            assert 'data-hides="rack" data-hides-when="tower"' in page
    assert '<div data-section="rack">' in client.get("/e/form?type=server").data.decode()


def test_the_rack_position_is_checked(client, h, admin):
    site, building, room, rack = place(client, h)
    def bad(**section):
        resp = client.post("/api/entities", json={"type": "shelf", "name": "x", "location_id": room["id"],
                                                  **{f"s.rack.{k}": v for k, v in section.items()}}, headers=h)
        assert resp.status_code == 400
        return resp.get_json()["error"]
    assert "unit it starts at" in bad(rack_id=rack["id"])
    assert "between 1 and 12" in bad(rack_id=rack["id"], position_u=13)
    assert "rack that exists" in bad(rack_id=room["id"], position_u=1)
    assert "front, rear" in bad(rack_id=rack["id"], position_u=1, face="side")
    # Nothing was made.
    assert client.get("/api/entities?type=shelf").get_json()["entities"] == []


def test_a_site_address_is_a_field_each(client, h, admin):
    site = make(client, h, "site", name="Office", **{"f.address": "1 Main St\nSuite 200", "f.city": "Springfield",
                                                     "f.region": "IL", "f.postal_code": "62704",
                                                     "f.country": "United States"})
    got = client.get(f"/api/entities/{site['id']}").get_json()["entity"]["fields"]
    assert (got["address"], got["city"], got["postal_code"]) == ("1 Main St\nSuite 200", "Springfield", "62704")
    assert "Springfield" in client.get("/locations?view=list").data.decode()


def test_the_form_explains_each_field(client, h, admin):
    form = client.get("/e/form?type=site").data.decode()
    for name in ("name", "status", "tags", "slug", "f-code", "f-address", "f-city", "f-region", "f-postal_code",
                 "f-country", "notes"):
        assert f'popovertarget="ef-{name}-help"' in form, name
        assert f'id="ef-{name}" ' in form or f'id="ef-{name}"' in form, name
        assert f'aria-describedby="ef-{name}-help"' in form, name
    assert "A short name for when the full one" in form and "[[its-slug]]" in form
    assert '<label class="field-label" for="ef-f-city">City</label>' in form


def retype(client, h, entity, type_, status=200, **body):
    resp = client.post(f"/api/entities/{entity['id']}", json={"type": type_, **body}, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def test_a_location_can_become_another_kind(client, h, admin):
    site = make(client, h, "site", name="Home")
    room = make(client, h, "room", name="Garage", location_id=site["id"], tags="lab", **{"f.code": "GAR"})
    server = make(client, h, "server", name="pve1", location_id=room["id"])
    got = retype(client, h, room, "building")["entity"]
    assert got["type"] == "building" and got["id"] == room["id"] and got["fields"]["code"] == "GAR"
    assert got["tags"] == ["lab"] and got["location"]["id"] == site["id"]
    path = client.get(f"/api/entities/{server['id']}").get_json()["entity"]["path"]
    assert [p["name"] for p in path] == ["Home", "Garage"]
    history = client.get(f"/api/entities/{room['id']}/history").get_json()["history"]
    assert {"field": "type", "label": "Type", "old": "Room", "new": "Building"} in history[0]["changes"]
    # A site is nowhere, so it leaves its location behind.
    got = retype(client, h, room, "site")["entity"]
    assert got["type"] == "site" and got["location"] is None


def test_a_new_kind_must_suit_where_it_is_and_what_is_in_it(client, h, admin):
    site, building, room, rack = place(client, h)
    assert "Rack A is in it and can't be in a building" in retype(client, h, room, "building", 400)["error"]
    closet = make(client, h, "room", name="Closet", location_id=building["id"])
    assert "can only be in a site" in retype(client, h, closet, "building", 400)["error"]
    # Moved at the same time, it fits.
    assert retype(client, h, closet, "building", location_id=site["id"])["entity"]["type"] == "building"
    assert "can't be changed into a server" in retype(client, h, room, "server", 400)["error"]
    server = make(client, h, "server", name="pve1")
    assert "can't be changed into a room" in retype(client, h, server, "room", 400)["error"]
    mount(client, h, rack, label="Switch", position_u=4)
    assert "1 thing is mounted in it" in retype(client, h, rack, "shelf", 400)["error"]
    # A record is left as it was when the change is refused.
    assert client.get(f"/api/entities/{rack['id']}").get_json()["entity"]["type"] == "rack"


def test_a_mounted_shelf_leaves_the_rack_before_it_becomes_a_room(client, h, admin):
    site, building, room, rack = place(client, h)
    shelf = make(client, h, "shelf", name="Shelf", location_id=rack["id"])
    mount(client, h, rack, entity_id=shelf["id"], position_u=2)
    assert "mounted in a rack" in retype(client, h, shelf, "room", 400, location_id=building["id"])["error"]


def test_a_shelf_made_a_rack_keeps_its_height_or_gets_the_default(client, h, admin):
    site, building, room, rack = place(client, h)
    cabinet = make(client, h, "shelf", name="Cabinet", location_id=room["id"], **{"f.height_u": 8})
    got = retype(client, h, cabinet, "rack")["entity"]
    assert got["fields"]["height_u"] == 8 and got["fields"]["numbering"] == "bottom"
    other = make(client, h, "shelf", name="Tray", location_id=room["id"])
    assert retype(client, h, other, "rack")["entity"]["fields"]["height_u"] == 42


def test_the_form_offers_the_other_kinds_and_redraws_for_one(client, h, admin):
    site, building, room, rack = place(client, h)
    form = client.get(f"/e/{room['id']}/form").data.decode()
    assert 'name="type" data-retype' in form and '<option value="building"' in form
    assert 'name="f.floor"' in form
    as_rack = client.get(f"/e/{room['id']}/form?type=rack").data.decode()
    assert 'name="f.height_u"' in as_rack and 'value="42"' in as_rack and 'name="f.floor"' not in as_rack
    assert '<option value="rack" selected>' in as_rack
    cluster = make(client, h, "cluster", name="Lab")
    assert "data-retype" not in client.get(f"/e/{cluster['id']}/form").data.decode()
    assert "data-retype" not in client.get("/e/form?type=room").data.decode()
