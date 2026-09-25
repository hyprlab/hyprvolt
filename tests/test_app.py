"""What the template guarantees.

These cover what is easy to break while reshaping the app and expensive to
notice later: the setup gate, CSRF, roles, the admin guard, and the
error shapes the client depends on. Add to them rather than replacing them.
"""
from .conftest import make, token_for


def test_fresh_install_steers_to_setup(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/setup")


def test_health_answers_before_setup(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_setup_runs_once(client, csrf, admin):
    assert client.get("/").status_code == 200
    again = client.post("/setup", json={"username": "x@example.com", "password": "password1"},
                        headers={"X-CSRF": csrf})
    assert again.status_code == 409


def test_post_without_csrf_is_refused(client, csrf, admin):
    resp = client.post("/api/entities", json={"type": "gadget", "name": "x"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_records_belong_to_the_instance(client, csrf, admin, second_user):
    """Everyone signed in reads everything; a viewer can't change it."""
    h = {"X-CSRF": csrf}
    shared = make(client, h, name="Shared")
    other, token = second_user
    assert other.get(f"/api/entities/{shared['id']}").status_code == 200
    assert other.get("/search?q=shar").get_json()["groups"][0]["items"][0]["title"] == "Shared"
    refused = other.post(f"/api/entities/{shared['id']}", json={"name": "Changed"}, headers={"X-CSRF": token})
    assert refused.status_code == 403 and "editor" in refused.get_json()["error"]


def test_an_editor_can_write(client, csrf, admin, second_user):
    other, token = second_user
    assert client.post("/admin/users/2/role", json={"role": "editor"},
                       headers={"X-CSRF": csrf}).get_json()["role"] == "editor"
    assert other.post("/api/entities", json={"type": "gadget", "name": "Mine"},
                      headers={"X-CSRF": token}).status_code == 200
    assert other.post("/admin/registration", json={"open": False},
                      headers={"X-CSRF": token}).status_code == 403


def test_sign_ups_get_the_default_role(client, csrf, admin, app):
    client.post("/admin/instance", json={"default_role": "editor"}, headers={"X-CSRF": csrf})
    assert client.post("/admin/instance", json={"default_role": "admin"},
                       headers={"X-CSRF": csrf}).status_code == 400
    stranger = app.test_client()
    token = token_for(stranger)
    stranger.post("/register", data={"_csrf": token, "username": "new@example.com",
                                     "password": "password1", "confirm": "password1"})
    from hyprprem.models import User
    with app.app_context():
        assert User.query.filter_by(username="new@example.com").one().role == "editor"


def test_every_route_declares_a_role(app):
    from hyprprem.permissions import undeclared_routes
    assert undeclared_routes(app) == []


def test_palette_search_groups_by_module(client, csrf, admin):
    h = {"X-CSRF": csrf}
    make(client, h, name="Findable 100%")
    make(client, h, "document", name="Findable notes")
    assert client.get("/search?q=F").get_json()["groups"] == []
    groups = client.get("/search?q=fin").get_json()["groups"]
    assert {g["label"]: [i["title"] for i in g["items"]] for g in groups} == \
        {"Gadgets": ["Findable 100%"], "Knowledge base": ["Findable notes"]}
    # LIKE wildcards in the query are matched literally.
    assert len(client.get("/search?q=0%25").get_json()["groups"]) == 1
    assert client.get("/search?q=__").get_json()["groups"] == []
    # Picking a record for a link: only the types asked for.
    picked = client.get("/search?q=fin&pick=1&types=document").get_json()["groups"]
    assert [i["title"] for g in picked for i in g["items"]] == ["Findable notes"]


def test_listing_filters_sorts_and_pages(client, csrf, app, admin):
    h = {"X-CSRF": csrf}
    for n in range(12):
        make(client, h, name=f"Item {n:02d}", tags="even" if n % 2 == 0 else "odd")
    client.post("/admin/instance", json={"items_per_page": 10}, headers=h)

    first = client.get("/example?sort=name&view=list").data.decode()
    assert first.index("Item 00") < first.index("Item 09")
    assert 'id="load-more"' in first and "Item 11" not in first

    second = client.get("/example?sort=name&view=list&page=2&partial=1").data.decode()
    assert "Item 11" in second and "<aside" not in second
    assert "That's everything" in second

    odd = client.get("/all?tag=odd&view=list").data.decode()
    assert "Item 01" in odd and "Item 02" not in odd
    found = client.get("/all?q=item+07&view=list").data.decode()
    assert "Item 07" in found and "Item 08" not in found


def test_admin_routes_refuse_a_plain_account(second_user):
    other, token = second_user
    assert other.post("/admin/registration", json={"open": False},
                      headers={"X-CSRF": token}).status_code == 403


def test_admin_cannot_delete_or_demote_itself(client, csrf, admin):
    h = {"X-CSRF": csrf}
    assert client.post("/admin/users", json={"username": "b@example.com", "password": "password1"},
                       headers=h).status_code == 200
    assert client.post("/admin/users/1/delete", headers=h).status_code == 400
    assert client.post("/admin/users/1/role", json={"role": "viewer"}, headers=h).status_code == 400


def test_deleting_a_user_keeps_what_they_wrote(client, csrf, admin, second_user):
    client.post("/admin/users/2/role", json={"role": "editor"}, headers={"X-CSRF": csrf})
    other, token = second_user
    theirs = make(other, {"X-CSRF": token}, name="Theirs")
    assert client.post("/admin/users/2/delete", headers={"X-CSRF": csrf}).status_code == 200
    assert client.get(f"/api/entities/{theirs['id']}").get_json()["entity"]["name"] == "Theirs"


def test_instance_settings_are_range_checked(client, csrf, admin):
    h = {"X-CSRF": csrf}
    assert client.post("/admin/instance", json={"worker_minutes": 99999}, headers=h).status_code == 400
    assert client.post("/admin/instance", json={"worker_minutes": "x"}, headers=h).status_code == 400
    assert client.post("/admin/instance", json={"worker_minutes": 30}, headers=h).status_code == 200


def test_registration_can_be_closed(client, csrf, admin, app):
    client.post("/admin/registration", json={"open": False}, headers={"X-CSRF": csrf})
    stranger = app.test_client()
    resp = stranger.get("/register")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")


def test_login_next_cannot_leave_the_site(client, csrf, admin):
    client.post("/logout", headers={"X-CSRF": csrf})
    for bad in ("https://example.net/", "//example.net/", "/\\example.net"):
        resp = client.post(f"/login?next={bad}", data={
            "_csrf": csrf, "username": admin["username"], "password": admin["password"],
        })
        assert resp.headers["Location"] in ("/", "http://localhost/"), bad
        client.post("/logout", headers={"X-CSRF": csrf})


def test_failed_sign_ins_are_throttled(client, csrf, admin):
    client.post("/logout", headers={"X-CSRF": csrf})
    data = {"_csrf": csrf, "username": admin["username"], "password": "wrong-password"}
    codes = [client.post("/login", data=data).status_code for _ in range(9)]
    assert codes[:8] == [401] * 8 and codes[8] == 429


def test_errors_are_json_for_the_api_and_a_page_for_people(client, csrf, admin):
    api = client.get("/api/entities/999", headers={"X-CSRF": csrf})
    assert api.status_code == 404 and "error" in api.get_json()
    page = client.get("/no-such-page")
    assert page.status_code == 404 and b"error-code" in page.data


def test_signed_out_api_calls_get_json_401(app, admin):
    stranger = app.test_client()
    resp = stranger.get("/api/entities/1", headers={"Accept": "application/json"})
    assert resp.status_code == 401 and "error" in resp.get_json()


def test_security_headers(client):
    resp = client.get("/login", follow_redirects=True)
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Cache-Control"] == "no-store"


def test_changelog_renders_in_the_about_tab(client, csrf, admin):
    from hyprprem import __version__
    body = client.get("/").data.decode()
    assert "Changelog" in body and __version__ in body


def test_admin_tab_shows_instance_counts(client, csrf, admin):
    """A dict key named like a dict method ("items") renders as the method in
    Jinja; the stats must come out as numbers."""
    make(client, {"X-CSRF": csrf}, name="One")
    body = client.get("/").data.decode()
    assert "1 user · 1 record" in body
    assert "built-in method" not in body


def test_a_client_that_accepts_anything_is_sent_to_sign_in(app, admin):
    resp = app.test_client().get("/", headers={"Accept": "*/*"})
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
