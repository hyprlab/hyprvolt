"""Settings > Modules, Settings > Custom fields, and the settings panes
modules add."""
import pytest

from hyprvolt.manifest import Pane
from hyprvolt.registry import EXTENSION

from .conftest import make


def test_an_admin_turns_a_module_off_and_on(client, h, admin):
    make(client, h, name="Blue box")
    assert client.post("/admin/modules/example", json={"enabled": False}, headers=h).get_json()["enabled"] is False
    assert client.get("/example").status_code == 404
    page = client.get("/").data.decode()
    assert 'data-module-toggle="example"' in page and "Gadgets" in page     # still listed in Settings
    client.post("/admin/modules/example", json={"enabled": True}, headers=h)
    assert "Blue box" in client.get("/example").data.decode()


def test_built_in_modules_stay_on(client, h, admin):
    resp = client.post("/admin/modules/documents", json={"enabled": False}, headers=h)
    assert resp.status_code == 400 and "built in" in resp.get_json()["error"]
    assert client.post("/admin/modules/nothing", json={"enabled": True}, headers=h).status_code == 404


def test_only_admins_manage_modules(client, h, admin, editor):
    other, oh = editor
    assert other.post("/admin/modules/example", json={"enabled": False}, headers=oh).status_code == 403
    assert 'data-module-toggle' not in other.get("/").data.decode()


def test_the_custom_fields_section_lists_fields_by_type(client, h, admin):
    client.post("/api/custom-fields", json={"entity_type": "rack", "label": "Asset tag", "kind": "text"}, headers=h)
    page = client.get("/").data.decode()
    section = page.split('id="settings-fields"')[1].split("</section>")[0]
    assert "Asset tag" in section and "c.asset_tag" in section and '<option value="rack">Racks</option>' in section


@pytest.fixture()
def pane(app):
    module = app.extensions[EXTENSION].module("example")
    module.settings_pane = Pane("example-settings", "Gadget settings", lambda: "<p>Gadget options</p>")
    yield
    module.settings_pane = None


def test_a_module_adds_a_settings_section(client, h, admin, pane):
    page = client.get("/").data.decode()
    assert 'data-section="example-settings"' in page and "<p>Gadget options</p>" in page


@pytest.fixture()
def hooks(app):
    """A job and a search provider on the example module, for these tests."""
    from hyprvolt.manifest import Job, SearchResult
    module = app.extensions[EXTENSION].module("example")
    ran = []
    module.jobs = (Job("count", lambda: ran.append(1) or 7, minutes=5),)
    module.search = lambda q, limit: [SearchResult(f"Port {q}", "Found by the example module", url="/example")]
    yield ran
    module.jobs = ()
    module.search = None


def test_module_jobs_run_when_due_and_only_when_on(app, client, h, admin, hooks):
    from hyprvolt.worker import run_once
    assert run_once(app)["example.count"] == 7
    assert "example.count" not in run_once(app)            # not due for five minutes
    assert run_once(app, force=True)["example.count"] == 7
    client.post("/admin/modules/example", json={"enabled": False}, headers=h)
    assert "example.count" not in run_once(app, force=True)
    assert hooks == [1, 1]


def test_module_search_providers_add_to_the_palette(client, h, admin, hooks):
    groups = client.get("/search?q=8080").get_json()["groups"]
    assert groups == [{"label": "Gadgets", "items": [
        {"id": None, "url": "/example", "title": "Port 8080", "meta": "Found by the example module"}]}]
    # Choosing a record for a link only offers records.
    assert client.get("/search?q=8080&pick=1").get_json()["groups"] == []


def _sidebar(page: str) -> tuple[list[str], list[str]]:
    side = page.split('id="sidebar"')[1].split('class="sidebar-foot"')[0]
    groups = [p.split('"')[0] for p in side.split('class="sidebar-group" data-group="')[1:]]
    modules = [p.split('"')[0] for p in side.split('data-module="')[1:]]
    return groups, modules


def test_an_admin_reorders_the_sidebar(client, h, admin, editor):
    groups, modules = _sidebar(client.get("/").data.decode())
    assert len(groups) > 1 and len(modules) > 2
    # The last group first, and in the first group its last module first.
    new_groups = [groups[-1]] + groups[:-1]
    new_modules = [modules[1], modules[0]] + modules[2:]
    assert client.post("/admin/sidebar-order", json={"groups": new_groups, "modules": new_modules},
                       headers=h).get_json() == {"ok": True}
    page = client.get("/").data.decode()
    got_groups, got_modules = _sidebar(page)
    assert got_groups == new_groups
    assert got_modules.index(modules[1]) < got_modules.index(modules[0])
    assert 'id="sidebar-order-reset" >' in page or 'id="sidebar-order-reset">' in page
    # A module the saved order doesn't name still shows, after the named ones.
    client.post("/admin/sidebar-order", json={"groups": new_groups, "modules": modules[1:]}, headers=h)
    assert modules[0] in _sidebar(client.get("/").data.decode())[1]
    # Names it doesn't have, and anyone but an admin, are refused.
    bad = client.post("/admin/sidebar-order", json={"groups": ["Nowhere"], "modules": []}, headers=h)
    assert bad.status_code == 400 and "Reload" in bad.get_json()["error"]
    other, oh = editor
    assert other.post("/admin/sidebar-order", json={"reset": True}, headers=oh).status_code == 403
    # Reset puts the modules' own order back.
    client.post("/admin/sidebar-order", json={"reset": True}, headers=h)
    assert _sidebar(client.get("/").data.decode()) == (groups, modules)
