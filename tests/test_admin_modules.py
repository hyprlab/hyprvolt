"""Settings > Modules, Settings > Custom fields, and the settings panes
modules add."""
import pytest

from hyprprem.manifest import Pane
from hyprprem.registry import EXTENSION

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
