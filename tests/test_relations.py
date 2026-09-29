"""Relationships, both directions, and the dependency walk."""
from .conftest import make


def link(client, h, kind, source, target, status=200):
    resp = client.post("/api/relationships", json={"kind": kind, "source_id": source["id"],
                                                   "target_id": target["id"]}, headers=h)
    assert resp.status_code == status, resp.get_json()
    return resp.get_json()


def test_a_link_reads_both_ways(client, h, admin):
    vm, host = make(client, h, name="vm1"), make(client, h, name="pve1")
    link(client, h, "runs_on", vm, host)
    from_vm = client.get(f"/api/entities/{vm['id']}/relationships").get_json()["relationships"]
    from_host = client.get(f"/api/entities/{host['id']}/relationships").get_json()["relationships"]
    assert [(r["label"], r["other"]["name"], r["outgoing"]) for r in from_vm] == [("runs on", "pve1", True)]
    assert [(r["label"], r["other"]["name"], r["outgoing"]) for r in from_host] == [("runs", "vm1", False)]
    # Both ends record it in their history.
    assert client.get(f"/api/entities/{host['id']}/history").get_json()["history"][0]["action"] == "linked"


def test_links_are_checked(client, h, admin):
    a = make(client, h, name="a")
    assert "itself" in link(client, h, "runs_on", a, a, 400)["error"]
    assert "kind" in link(client, h, "loves", a, make(client, h, name="b"), 400)["error"]
    assert "exist" in client.post("/api/relationships", json={"kind": "runs_on", "source_id": a["id"],
                                                               "target_id": 999}, headers=h).get_json()["error"]


def test_removing_a_link_can_be_undone(client, h, admin):
    a, b = make(client, h, name="a"), make(client, h, name="b")
    rel = link(client, h, "depends_on", a, b)["relationship"]
    undo = client.post(f"/api/relationships/{rel['id']}/delete", headers=h).get_json()["undo"]
    assert client.get(f"/api/entities/{a['id']}/relationships").get_json()["relationships"] == []
    client.post(undo["url"], json=undo["body"], headers=h)
    assert len(client.get(f"/api/entities/{a['id']}/relationships").get_json()["relationships"]) == 1


def test_removing_a_link_asks_first(client, h, admin):
    a, b = make(client, h, name="web"), make(client, h, name="db")
    link(client, h, "depends_on", a, b)
    tab = client.get(f"/e/{a['id']}/sheet?tab=relationships").get_data(as_text=True)
    assert 'data-confirm="Remove this link?"' in tab and "web and db will no longer be linked" in tab
    assert 'id="confirm-modal"' in client.get("/").get_data(as_text=True)

def test_a_deleted_record_drops_out_of_links(client, h, admin):
    a, b = make(client, h, name="a"), make(client, h, name="b")
    link(client, h, "depends_on", a, b)
    client.post(f"/api/entities/{b['id']}/delete", headers=h)
    assert client.get(f"/api/entities/{a['id']}/relationships").get_json()["relationships"] == []
    client.post(f"/api/entities/{b['id']}/restore", headers=h)
    assert len(client.get(f"/api/entities/{a['id']}/relationships").get_json()["relationships"]) == 1


def names(tree):
    return [(n["name"], n["label"], [c for c in names(n["children"])], n["cycle"], n["repeat"]) for n in tree]


def test_what_breaks_if_this_goes_down(client, h, admin):
    ups, host, vm, app_, docs = (make(client, h, name=n) for n in ("ups", "host", "vm", "app", "docs"))
    link(client, h, "powered_by", host, ups)
    link(client, h, "runs_on", vm, host)
    link(client, h, "hosted_by", app_, vm)
    link(client, h, "documented_by", host, docs)      # no impact: not followed
    tree = client.get(f"/api/entities/{ups['id']}/dependencies").get_json()["tree"]
    assert names(tree) == [("host", "powers", [("vm", "runs", [("app", "hosts", [], False, False)], False, False)],
                            False, False)]
    needs = client.get(f"/api/entities/{app_['id']}/dependencies?direction=dependencies").get_json()["tree"]
    assert needs[0]["name"] == "vm" and needs[0]["children"][0]["children"][0]["name"] == "ups"


def test_the_walk_survives_cycles_and_diamonds(client, h, admin):
    a, b, c, d = (make(client, h, name=n) for n in "abcd")
    link(client, h, "depends_on", b, a)
    link(client, h, "depends_on", c, b)
    link(client, h, "depends_on", a, c)                # a -> c -> b -> a
    link(client, h, "depends_on", d, a)
    link(client, h, "depends_on", d, b)                # d needs a and b
    tree = client.get(f"/api/entities/{a['id']}/dependencies").get_json()["tree"]
    flat = []

    def visit(nodes, depth=0):
        for n in nodes:
            flat.append((depth, n["name"], n["cycle"], n["repeat"]))
            visit(n["children"], depth + 1)
    visit(tree)
    assert any(name == "a" and cycle for _, name, cycle, _ in flat)
    assert sum(1 for _, name, _, repeat in flat if name == "d" and not repeat) == 1


def test_a_viewer_cannot_link(client, h, admin, viewer):
    a, b = make(client, h, name="a"), make(client, h, name="b")
    other, oh = viewer
    assert other.post("/api/relationships", json={"kind": "runs_on", "source_id": a["id"],
                                                  "target_id": b["id"]}, headers=oh).status_code == 403
    assert other.get(f"/api/entities/{a['id']}/dependencies").status_code == 200


def test_the_dependency_view_says_what_each_record_is(client, h, admin):
    host = make(client, h, "hypervisor", name="pve1")
    vm = make(client, h, "vm", name="docker1", **{"f.host": host["id"]})
    make(client, h, "service", name="Jellyfin", **{"f.host": vm["id"]})
    tab = client.get(f"/e/{host['id']}/sheet?tab=relationships").data.decode()
    assert 'deptree-kind">Virtual machine</span>' in tab and 'deptree-kind">Service</span>' in tab
    tree = client.get(f"/api/entities/{host['id']}/dependencies").get_json()["tree"]
    assert tree[0]["type_label"] == "Virtual machine" and tree[0]["children"][0]["type_label"] == "Service"


def _chain(client, h):
    srv = make(client, h, "server", name="srv1")
    hv = make(client, h, "hypervisor", name="pve1", **{"f.host": srv["id"]})
    web = make(client, h, "vm", name="web", **{"f.host": hv["id"]})
    db = make(client, h, "vm", name="db", **{"f.host": hv["id"]})
    client.post("/api/relationships", json={"kind": "depends_on", "source_id": web["id"],
                                            "target_id": db["id"]}, headers=h)
    return srv, hv, web, db


def test_the_dependency_view_switches_to_a_diagram(client, h, admin):
    srv, hv, web, db = _chain(client, h)
    tab = client.get(f"/e/{hv['id']}/sheet?tab=relationships").data.decode()
    # The diagram shows first; List is a click away.
    assert 'data-views="dependencies"' in tab and '<div data-view="diagram">' in tab
    assert '<div data-view="list" hidden>' in tab and 'value="diagram" checked' in tab
    drawing = tab[tab.index('data-view="diagram"'):]
    assert "What it needs" in drawing and "What breaks if this goes down" in drawing
    # One box each, web reached both from pve1 and through db.
    for name in ("srv1", "pve1", "web", "db"):
        assert drawing.count(f">{name}</text>") == 1, name
    assert drawing.count('<g class="diagram-link') == 4 and "is-center" in drawing


def test_a_record_that_needs_something_after_a_sibling_sits_below_it(client, h, admin):
    from hyprvolt.core import depmap, relations
    from hyprvolt.core.models import Entity
    from hyprvolt.models import db as sa
    srv, hv, web, db = _chain(client, h)
    with client.application.test_request_context():
        from flask_login import login_user
        from hyprvolt.models import User
        login_user(User.query.first())
        entity = sa.session.get(Entity, hv["id"])
        rows, _ = depmap._side(relations.walk(entity, "dependents"), entity.id)
    assert {d: [e.name for e in r] for d, r in rows.items()} == {1: ["db"], 2: ["web"]}


def test_a_loop_is_drawn_dashed_and_a_lone_record_has_no_switch(client, h, admin):
    a = make(client, h, "service", name="api")
    b = make(client, h, "service", name="auth")
    client.post("/api/relationships", json={"kind": "depends_on", "source_id": a["id"], "target_id": b["id"]}, headers=h)
    client.post("/api/relationships", json={"kind": "depends_on", "source_id": b["id"], "target_id": a["id"]}, headers=h)
    tab = client.get(f"/e/{a['id']}/sheet?tab=relationships").data.decode()
    assert "diagram-link--loose" in tab and "A dashed line leads back into a loop." in tab
    lonely = make(client, h, "vm", name="spare")
    alone = client.get(f"/e/{lonely['id']}/sheet?tab=relationships").data.decode()
    assert "data-views" not in alone and '<div data-view="list">' in alone and "Nothing depends on it." in alone


def test_a_crowded_row_draws_every_record(client, h, admin):
    hv = make(client, h, "hypervisor", name="pve1")
    guests = [make(client, h, "vm", name=f"vm{n}", **{"f.host": hv["id"]}) for n in range(9)]
    make(client, h, "service", name="app", **{"f.host": guests[6]["id"]})
    tab = client.get(f"/e/{hv['id']}/sheet?tab=relationships").data.decode()
    drawing = tab[tab.index('data-view="diagram"'):]
    assert all(f">vm{n}</text>" in drawing for n in range(9)) and ">app</text>" in drawing
    assert "more in the list" not in drawing and "data-zoom" in drawing
