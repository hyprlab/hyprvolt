"""The module registry: discovery, validation, ordering, turning modules off,
and the migration helpers modules use."""
import pytest
from flask import Blueprint

from hyprvolt import registry as reg_mod
from hyprvolt.core.models import EntityDetail
from hyprvolt.manifest import EntityType, Field, FormSection, Module, RelationKind, Step
from hyprvolt.models import db, set_setting
from hyprvolt.permissions import role


def fresh():
    return reg_mod.Registry()


def problems(module, reg=None):
    return reg_mod.validate(module, reg or fresh())


class ToolDetail(EntityDetail, db.Model):
    __tablename__ = "test_tools"
    size = db.Column(db.Integer)


# ———— Discovery ————

def test_discovery_finds_the_example_module(app):
    reg = app.extensions[reg_mod.EXTENSION]
    assert "example" in reg.modules
    assert reg.type("gadget").module == "example"
    assert not reg.errors


def test_broken_modules_are_left_out_with_a_reason():
    reg = reg_mod.discover(["tests.broken_modules"], strict=False)
    assert reg.modules == {}
    assert set(reg.errors) == {"tests.broken_modules.nomanifest", "tests.broken_modules.raises", "badfield"}
    assert "hologram" in reg.errors["badfield"]
    assert "exports no" in reg.errors["tests.broken_modules.nomanifest"]


def test_strict_mode_raises_on_a_broken_module():
    with pytest.raises(reg_mod.ManifestError):
        reg_mod.discover(["tests.broken_modules"], strict=True)


# ———— Validation ————

def test_a_good_manifest_passes():
    m = Module(id="tools", name="Tools", types=(
        EntityType("tool", "Tool", "Tools", detail=ToolDetail, fields=(Field("size", "Size", "integer"),)),))
    assert problems(m) == []


@pytest.mark.parametrize("module, expected", [
    (Module(id="Bad Id", name="x"), "lower-case"),
    (Module(id="search", name="x"), "reserved"),
    (Module(id="tools", name=""), "no name"),
    (Module(id="tools", name="x", icon='<path onload="x()"/>'), "SVG shapes"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools", fields=(Field("size", "Size"),)),)),
     "no detail model"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools", detail=ToolDetail,
                                                    fields=(Field("weight", "Weight"),)),)), "no column"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools", detail=ToolDetail,
                                                    fields=(Field("size", "Size", "select"),)),)), "no options"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools", detail=ToolDetail,
                                                    fields=(Field("name", "Name"),)),)), "already has"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools"), EntityType("tool", "Tool", "Tools"))),
     "already exists"),
    (Module(id="tools", name="x", relation_kinds=(RelationKind("runs_on", "runs on", "runs"),)), "already exists"),
    (Module(id="tools", name="x", relation_kinds=(RelationKind("feeds", "feeds", "fed by", impact="lots"),)),
     "impact"),
    (Module(id="tools", name="x", migrations=(Step("one", lambda m: None), Step("one", lambda m: None))),
     "appears twice"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools", detail=ToolDetail,
                                                    fields=(Field("size", "Size", relation="runs_on"),)),)),
     "must be a ref"),
    (Module(id="tools", name="x", types=(EntityType("tool", "Tool", "Tools", traits="rackmount"),)), "traits"),
    (Module(id="tools", name="x", form_sections=(FormSection("Bad Key", "x", str, str),)), "form section key"),
    (Module(id="tools", name="x", form_sections=(FormSection("extra", "x", str, None),)), "render and save"),
])
def test_bad_manifests_are_refused(module, expected):
    found = problems(module)
    assert found and expected in "; ".join(found), found


def test_a_type_key_can_only_be_taken_once(app):
    reg = app.extensions[reg_mod.EXTENSION]
    clash = Module(id="other", name="Other", types=(EntityType("gadget", "Gadget", "Gadgets"),))
    assert "already exists" in "; ".join(problems(clash, reg))


def test_a_blueprint_route_without_a_role_is_refused():
    bp = Blueprint("tools", __name__)

    @bp.route("/open")
    def wide_open():
        return "anyone"

    @bp.route("/fine")
    @role("viewer")
    def fine():
        return "ok"

    found = problems(Module(id="tools", name="Tools", blueprint=bp))
    assert found and "tools.wide_open" in found[0] and "tools.fine" not in found[0]


def test_the_blueprint_is_named_after_the_module():
    found = problems(Module(id="tools", name="Tools", blueprint=Blueprint("gear", __name__)))
    assert "named 'tools'" in found[0]


def test_missing_requirements_and_circles_are_refused():
    reg = reg_mod.load(fresh(), [Module(id="aa", name="A", requires=("zz",))])
    assert "aa" in reg.errors and not reg.modules

    reg = reg_mod.load(fresh(), [Module(id="aa", name="A", requires=("bb",)),
                                 Module(id="bb", name="B", requires=("aa",))])
    assert "circle" in reg.errors["modules"] and not reg.modules


def test_a_ref_field_must_point_at_a_known_type():
    m = Module(id="tools", name="Tools", types=(
        EntityType("tool", "Tool", "Tools", detail=ToolDetail,
                   fields=(Field("size", "Size", "ref", types=("spaceship",)),)),))
    reg = reg_mod.load(fresh(), [m])
    assert "spaceship" in reg.errors["tools"]


def test_a_field_kept_as_a_link_needs_no_column_but_a_known_kind():
    ok = Module(id="tools", name="Tools", types=(
        EntityType("tool", "Tool", "Tools", fields=(
            Field("host", "Host", "ref", types=("tool",), relation="runs_on"),)),))
    assert problems(ok) == []
    reg = reg_mod.load(fresh(), [ok])
    assert not reg.errors
    bad = Module(id="tools", name="Tools", types=(
        EntityType("tool", "Tool", "Tools", fields=(
            Field("host", "Host", "ref", types=("tool",), relation="orbits"),)),))
    assert "orbits" in reg_mod.load(fresh(), [bad]).errors["tools"]


def test_a_form_section_key_can_only_be_taken_once(app):
    reg = app.extensions[reg_mod.EXTENSION]
    clash = Module(id="other", name="Other", form_sections=(FormSection("sticker", "x", str, str),))
    assert "already exists" in "; ".join(problems(clash, reg))


# ———— Order ————

def test_migration_order_follows_requires_then_id():
    mods = [Module(id="net", name="N", requires=("hw",)), Module(id="hw", name="H"),
            Module(id="apps", name="A"), Module(id="virt", name="V", requires=("hw", "net"))]
    assert [m.id for m in reg_mod.migration_order(mods)] == ["apps", "hw", "net", "virt"]
    # A newcomer doesn't reorder the others.
    mods.append(Module(id="aaa", name="Z", requires=("virt",)))
    assert [m.id for m in reg_mod.migration_order(mods)] == ["apps", "hw", "net", "virt", "aaa"]


def test_sidebar_order_follows_group_then_order():
    reg = reg_mod.load(fresh(), [
        Module(id="docs", name="Docs", group="Knowledge", order=90),
        Module(id="net", name="Network", group="Infrastructure", order=30),
        Module(id="loc", name="Locations", group="Infrastructure", order=10),
    ])
    assert [m.id for m in reg.sidebar_order()] == ["loc", "net", "docs"]


# ———— Turning a module off ————

def test_modules_are_on_until_an_admin_turns_them_off(app):
    reg = app.extensions[reg_mod.EXTENSION]
    with app.test_request_context():
        assert reg.is_enabled("example")
    with app.app_context():
        set_setting("module:example:enabled", "0")
    with app.test_request_context():
        assert not reg.is_enabled("example")
        assert "gadget" not in reg.enabled_type_keys()
        # Its model and table are still there.
        assert db.inspect(db.engine).has_table("example_gadgets")


def test_a_module_is_off_while_one_it_requires_is(app, client, h, admin):
    reg = reg_mod.load(fresh(), [Module(id="aa", name="A"), Module(id="bb", name="B", requires=("aa",))])
    with app.test_request_context():
        set_setting("module:aa:enabled", "0")
        assert reg.enabled_ids() == set()
        assert reg.switched_on() == {"bb"}
    # Through the admin routes: Locations can't come back on before its
    # requirement, and the pane says why.
    real = app.extensions[reg_mod.EXTENSION]
    needs = [m for m in real.modules.values() if m.requires]
    if needs:
        m = needs[0]
        need = real.module(m.requires[0])
        client.post(f"/admin/modules/{need.id}", json={"enabled": False}, headers=h)
        page = client.get("/").data.decode()
        assert f"Off while {need.name}" in page
        resp = client.post(f"/admin/modules/{m.id}", json={"enabled": True}, headers=h)
        assert resp.status_code == 400 and "Turn that on first" in resp.get_json()["error"]


# ———— Migrations ————

def test_migration_helpers_are_safe_to_run_twice(app):
    from hyprvolt.migrate import Migrator
    calls = []
    with app.app_context():
        m = Migrator("example")
        for _ in range(2):
            m.add_column("example_gadgets", "weight", "INTEGER")
            m.add_index("ix_example_weight", "example_gadgets", ["weight"])
            m.once("backfill", lambda: calls.append(1))
        assert m.has_column("example_gadgets", "weight")
        assert calls == [1]


def test_module_steps_run_after_the_core_in_order(app):
    """_migrate runs every module's steps in migration order at boot."""
    ran = []
    reg = reg_mod.load(fresh(), [
        Module(id="zz", name="Z", migrations=(Step("1", lambda m: ran.append(("zz", m.owner))),)),
        Module(id="aa", name="A", requires=("zz",), migrations=(Step("1", lambda m: ran.append(("aa", m.owner))),)),
    ])
    from hyprvolt import _migrate
    app.extensions[reg_mod.EXTENSION] = reg
    with app.app_context():
        _migrate(app)
    assert ran == [("zz", "zz"), ("aa", "aa")]


def test_a_type_label_inside_a_sentence():
    assert EntityType("vm", "Virtual machine", "Virtual machines").text() == "virtual machine"
    assert EntityType("nas", "NAS", "NAS").text(plural=True) == "NAS"
    assert EntityType("lxc", "LXC container", "LXC containers").text() == "LXC container"
    assert EntityType("docker_host", "Docker host", "Docker hosts", proper=True).text(True) == "Docker hosts"
    assert EntityType("a", "A", "As").text() == "a"
