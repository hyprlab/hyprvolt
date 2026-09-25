"""What the template guarantees.

These cover what is easy to break while reshaping the app and expensive to
notice later: the setup gate, CSRF, roles, the admin guard, and the
error shapes the client depends on. Add to them rather than replacing them.
"""
from .conftest import token_for


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
    resp = client.post("/items", json={"title": "x"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_item_round_trip(client, csrf, admin):
    h = {"X-CSRF": csrf}
    item = client.post("/items", json={"title": "Write it down", "body": "Later."}, headers=h).get_json()["item"]
    assert client.get(f"/items/{item['id']}").get_json()["item"]["title"] == "Write it down"

    updated = client.post(f"/items/{item['id']}", json={"pinned": True, "done": True}, headers=h).get_json()["item"]
    assert updated["pinned"] and updated["done"]

    deleted = client.post(f"/items/{item['id']}/delete", headers=h).get_json()
    assert client.get(f"/items/{item['id']}", headers=h).status_code == 404

    restored = client.post("/items/restore", json=deleted["item"], headers=h).get_json()["item"]
    assert restored["title"] == "Write it down" and restored["pinned"]


def test_item_needs_a_title(client, csrf, admin):
    resp = client.post("/items", json={"title": "   "}, headers={"X-CSRF": csrf})
    assert resp.status_code == 400
    assert "title" in resp.get_json()["error"].lower()


def test_records_belong_to_the_instance(client, csrf, admin, second_user):
    """Everyone signed in reads everything; a viewer can't change it."""
    shared = client.post("/items", json={"title": "Shared"}, headers={"X-CSRF": csrf}).get_json()["item"]
    other, token = second_user
    assert other.get(f"/items/{shared['id']}", headers={"X-CSRF": token}).status_code == 200
    assert len(other.get("/search?q=shar").get_json()["results"]) == 1
    refused = other.post(f"/items/{shared['id']}", json={"title": "Changed"}, headers={"X-CSRF": token})
    assert refused.status_code == 403 and "editor" in refused.get_json()["error"]
    assert other.post("/items", json={"title": "New"}, headers={"X-CSRF": token}).status_code == 403


def test_an_editor_can_write(client, csrf, admin, second_user):
    other, token = second_user
    assert client.post("/admin/users/2/role", json={"role": "editor"},
                       headers={"X-CSRF": csrf}).get_json()["role"] == "editor"
    assert other.post("/items", json={"title": "Mine"}, headers={"X-CSRF": token}).status_code == 200
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


def test_search(client, csrf, admin):
    client.post("/items", json={"title": "Findable 100%"}, headers={"X-CSRF": csrf})
    assert client.get("/search?q=F").get_json()["results"] == []
    assert len(client.get("/search?q=fin").get_json()["results"]) == 1
    # LIKE wildcards in the query are matched literally.
    assert len(client.get("/search?q=0%25").get_json()["results"]) == 1
    assert client.get("/search?q=__").get_json()["results"] == []


def test_listing_filters_sorts_and_pages(client, csrf, app, admin):
    h = {"X-CSRF": csrf}
    for n in range(12):
        client.post("/items", json={"title": f"Item {n:02d}"}, headers=h)
    client.post("/admin/instance", json={"items_per_page": 10}, headers=h)

    first = client.get("/?sort=title&view=list").data.decode()
    assert first.index("Item 00") < first.index("Item 09")
    assert 'id="load-more"' in first and "Item 11" not in first

    second = client.get("/?sort=title&view=list&page=2&partial=1").data.decode()
    assert "Item 11" in second and "<aside" not in second
    assert "That's everything" in second


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
    other.post("/items", json={"title": "Theirs"}, headers={"X-CSRF": token})
    assert client.post("/admin/users/2/delete", headers={"X-CSRF": csrf}).status_code == 200
    from hyprprem.models import Item
    with client.application.app_context():
        assert Item.query.count() == 1


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
    api = client.get("/items/999", headers={"X-CSRF": csrf})
    assert api.status_code == 404 and "error" in api.get_json()
    page = client.get("/no-such-page")
    assert page.status_code == 404 and b"error-code" in page.data


def test_signed_out_api_calls_get_json_401(app, admin):
    stranger = app.test_client()
    resp = stranger.get("/items/1", headers={"Accept": "application/json"})
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
    client.post("/items", json={"title": "One"}, headers={"X-CSRF": csrf})
    body = client.get("/").data.decode()
    assert "1 user · 1 record" in body
    assert "built-in method" not in body


def test_a_client_that_accepts_anything_is_sent_to_sign_in(app, admin):
    resp = app.test_client().get("/", headers={"Accept": "*/*"})
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
