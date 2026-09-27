"""Backup jobs: runs reported by a script or by hand, a status that follows
them, overdue jobs marked by the worker, and the Backups tab of what they
back up."""
from datetime import timedelta

from .conftest import make
from .test_reminders import days, due
from .test_tokens import bearer, made


def history(client, entity_id):
    return client.get(f"/api/entities/{entity_id}/history").get_json()["history"]


def status(client, entity_id):
    return client.get(f"/api/entities/{entity_id}").get_json()["entity"]["status"]


def lab(client, h, **fields):
    vm = make(client, h, "vm", name="homeassistant")
    nas = make(client, h, "nas", name="nas1")
    job = make(client, h, "backup_job", name="Nightly", **{"f.backs_up": vm["id"], "f.saved_to": nas["id"],
                                                          **{"f." + k: v for k, v in fields.items()}})
    return job, vm, nas


def test_a_script_reports_runs_and_the_status_follows(app, client, h, admin):
    job, vm, nas = lab(client, h)
    assert job["status"] == "new"
    token, _ = made(client, h, read_only=False, name="pbs hook")
    script = app.test_client()
    url = f"/backup_jobs/{job['id']}/runs"
    got = script.post(url, json={"result": "success", "note": "12 GB"}, headers=bearer(token)).get_json()
    assert got["status"] == "ok" and got["run"]["by"] == "pbs hook"
    assert script.post(url, json={"result": "failed"}, headers=bearer(token)).get_json()["status"] == "failing"
    assert script.post(url, json={"result": "success"}, headers=bearer(token)).get_json()["status"] == "ok"
    # Three runs, but only the status changes reach the history.
    changes = [c for r in history(client, job["id"]) for c in r["changes"] if c["label"] == "Status"]
    assert [c["new"] for c in changes] == ["Succeeding", "Failing", "Succeeding"]
    assert len(script.get(url, headers=bearer(token)).get_json()["runs"]) == 3
    bad = script.post(url, json={"result": "fine"}, headers=bearer(token))
    assert bad.status_code == 400 and "success, warning or failed" in bad.get_json()["error"]
    read_only, _ = made(client, h, read_only=True, name="reader")
    assert script.post(url, json={"result": "success"}, headers=bearer(read_only)).status_code == 403


def test_a_job_without_a_recent_success_is_overdue(app, client, h, admin):
    job, vm, nas = lab(client, h, interval_hours=24)
    long_ago = (client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success", "at": "2020-01-01T02:00:00Z"},
                            headers=h).get_json())
    assert long_ago["status"] == "stale"
    assert ">Nightly<" in client.get("/backup_jobs?f=trouble&view=list").data.decode()
    future = client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success", "at": "2999-01-01T00:00:00"},
                         headers=h)
    assert future.status_code == 400 and "future" in future.get_json()["error"]
    assert client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success"}, headers=h).get_json()["status"] == "ok"
    # Time passes: the worker's pass marks it.
    from hyprvolt.models import db
    from hyprvolt.modules.backup_jobs import views
    from hyprvolt.modules.backup_jobs.models import BackupRun
    with app.app_context():
        for run in BackupRun.query:
            run.at -= timedelta(hours=40)
        db.session.commit()
        assert views.refresh() == 1
        db.session.commit()
    assert status(client, job["id"]) == "stale"
    assert "Overdue" in client.get("/").data.decode()


def test_a_paused_job_keeps_its_status(client, h, admin):
    job, vm, nas = lab(client, h)
    client.post(f"/api/entities/{job['id']}", json={"status": "paused"}, headers=h)
    assert client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "failed"}, headers=h).get_json()["status"] == "paused"


def test_a_run_removed_comes_back_with_undo(client, h, admin):
    job, vm, nas = lab(client, h)
    client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success"}, headers=h)
    run = client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "failed", "note": "disk full"}, headers=h)
    undo = client.post(f"/backup_jobs/runs/{run.get_json()['run']['id']}/delete", headers=h).get_json()["undo"]
    assert status(client, job["id"]) == "ok"
    client.post(undo["url"], json=undo["body"], headers=h)
    assert status(client, job["id"]) == "failing"
    tab = client.get(f"/e/{job['id']}/sheet?tab=runs").data.decode()
    assert "disk full" in tab and "Record a run" in tab and "Authorization: Bearer $HYPRVOLT_TOKEN" in tab


def test_what_is_backed_up_has_a_backups_tab(client, h, admin):
    job, vm, nas = lab(client, h)
    client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success"}, headers=h)
    tab = client.get(f"/e/{vm['id']}/sheet?tab=backups").data.decode()
    assert ">Nightly</a>" in tab and "Last succeeded" in tab and "Succeeding" in tab
    assert 'data-tab="backups"' in client.get(f"/e/{vm['id']}/sheet").data.decode()
    assert 'data-tab="backups"' not in client.get(f"/e/{nas['id']}/sheet").data.decode()
    # The job needs the NAS it writes to.
    deps = client.get(f"/api/entities/{nas['id']}/dependencies").get_json()
    assert "Nightly" in str(deps["tree"])


def test_the_next_restore_test_is_reminded_of(client, h, admin):
    lab(client, h, restore_due=days(10))
    assert ">Nightly</a>" in due(client) and "Next restore test" in due(client)


def test_only_the_newest_runs_are_kept(app, client, h, admin, monkeypatch):
    from hyprvolt.models import db
    from hyprvolt.modules.backup_jobs import views
    from hyprvolt.modules.backup_jobs.models import BackupRun
    job, vm, nas = lab(client, h)
    for n in range(5):
        client.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success", "note": str(n)}, headers=h)
    monkeypatch.setattr(views, "KEEP_RUNS", 3)
    with app.app_context():
        views.refresh()
        db.session.commit()
        assert sorted(r.note for r in BackupRun.query) == ["2", "3", "4"]


def test_viewers_can_not_report(client, h, admin, viewer):
    job, vm, nas = lab(client, h)
    other, vh = viewer
    assert other.post(f"/backup_jobs/{job['id']}/runs", json={"result": "success"}, headers=vh).status_code == 403
    assert "Record a run" not in other.get(f"/e/{job['id']}/sheet?tab=runs").data.decode()
    assert other.get(f"/backup_jobs/{job['id']}/runs").status_code == 200
