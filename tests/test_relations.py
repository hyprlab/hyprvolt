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
