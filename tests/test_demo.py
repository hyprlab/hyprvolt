"""flask seed-demo and the dashboard's Load a demo homelab."""


def test_the_demo_fills_an_empty_instance(app, client, h, admin):
    assert "Load a demo homelab" in client.get("/").data.decode()
    resp = client.post("/admin/seed-demo", headers=h)
    assert resp.status_code == 200 and resp.get_json()["records"] > 10
    rack = [e for e in client.get("/api/entities?type=rack").get_json()["entities"]][0]
    assert rack["name"] == "Rack 1"
    elevation = client.get(f"/locations/racks/{rack['id']}/elevation").get_json()
    assert elevation["conflicts"] == [] and elevation["rack"]["used_u"] > 10
    # Documents link to the rack, and their [[slugs]] resolve.
    docs = client.get(f"/e/{rack['id']}/sheet?tab=documents").data.decode()
    assert "Power outage checklist" in docs
    doc = client.get("/api/entities?type=document&q=lab+overview").get_json()["entities"][0]
    body = client.get(f"/e/{doc['id']}/sheet").data.decode()
    assert f'href="/e/{rack["id"]}"' in body and "<s>" not in body
    # The history says who.
    history = client.get(f"/api/entities/{rack['id']}/history").get_json()["history"]
    assert history[-1]["user"] == "Ada"
    # Only once.
    again = client.post("/admin/seed-demo", headers=h)
    assert again.status_code == 409 and "empty" in again.get_json()["error"]


def test_the_command(app, client, h, admin):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed-demo"])
    assert result.exit_code == 0 and "records" in result.output
    assert runner.invoke(args=["seed-demo"]).exit_code != 0
    assert runner.invoke(args=["seed-demo", "--force"]).exit_code == 0


def test_only_admins_load_the_demo(client, h, admin, editor):
    other, oh = editor
    assert other.post("/admin/seed-demo", headers=oh).status_code == 403
    assert "Load a demo homelab" not in other.get("/").data.decode()
