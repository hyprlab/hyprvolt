"""Attachments: upload, download, limits, delete with Undo, the purge, and
the backup that carries them."""
import io
import sqlite3
import tarfile

from .conftest import make


def upload(client, h, entity_id, data=b"hello", name="notes.txt", ctype="text/plain"):
    return client.post(f"/api/entities/{entity_id}/attachments", headers=h,
                       data={"file": (io.BytesIO(data), name, ctype)}, content_type="multipart/form-data")


def test_upload_and_download(app, client, h, admin):
    box = make(client, h, name="Box")
    resp = upload(client, h, box["id"], name="../../etc/passwd.txt")
    att = resp.get_json()["attachments"][0]
    assert att["filename"] == "passwd.txt" and att["size"] == 5
    got = client.get(att["url"])
    assert got.data == b"hello" and "sandbox" in got.headers["Content-Security-Policy"]
    listed = client.get(f"/api/entities/{box['id']}/attachments").get_json()["attachments"]
    assert [a["id"] for a in listed] == [att["id"]]
    # Stored under a generated name inside the data directory.
    from pathlib import Path
    stored = list((Path(app.config["DATA_DIR"]) / "attachments").rglob("*"))
    assert any(p.is_file() and p.read_bytes() == b"hello" for p in stored)


def test_anything_but_images_pdfs_and_text_downloads(client, h, admin):
    box = make(client, h, name="Box")
    att = upload(client, h, box["id"], b"<script>x</script>", "page.html", "text/html").get_json()["attachments"][0]
    got = client.get(att["url"])
    assert got.headers["Content-Type"] == "application/octet-stream"
    assert got.headers["Content-Disposition"].startswith("attachment")


def test_the_size_limit_is_an_instance_setting(client, h, admin):
    client.post("/admin/instance", json={"max_upload_mb": 1}, headers=h)
    box = make(client, h, name="Box")
    resp = upload(client, h, box["id"], b"x" * (1024 * 1024 + 1))
    assert resp.status_code in (400, 413) and "1 MB" in resp.get_json()["error"]
    assert client.get(f"/api/entities/{box['id']}/attachments").get_json()["attachments"] == []


def test_delete_undo_and_purge(app, client, h, admin):
    box = make(client, h, name="Box")
    att = upload(client, h, box["id"]).get_json()["attachments"][0]
    undo = client.post(f"/api/attachments/{att['id']}/delete", headers=h).get_json()["undo"]
    assert client.get(att["url"]).status_code == 404
    client.post(undo["url"], json=undo["body"], headers=h)
    assert client.get(att["url"]).status_code == 200

    client.post(f"/api/attachments/{att['id']}/delete", headers=h)
    from hyprvolt.core.records import purge
    from hyprvolt.models import db
    with app.app_context():
        assert purge(older_than_days=0) == 1
        db.session.commit()
    assert client.post(undo["url"], json={}, headers=h).status_code == 404


def test_viewers_download_but_cannot_upload(client, h, admin, viewer):
    box = make(client, h, name="Box")
    att = upload(client, h, box["id"]).get_json()["attachments"][0]
    other, oh = viewer
    assert other.get(att["url"]).status_code == 200
    assert upload(other, oh, box["id"]).status_code == 403
    assert other.post(f"/api/attachments/{att['id']}/delete", headers=oh).status_code == 403


def test_backup_archives_the_database_and_attachments(app, client, h, admin, tmp_path):
    box = make(client, h, name="Box")
    upload(client, h, box["id"], b"config file")
    dest = tmp_path / "backup.tar.gz"
    result = app.test_cli_runner().invoke(args=["backup", str(dest)])
    assert result.exit_code == 0, result.output
    with tarfile.open(dest) as tar:
        names = tar.getnames()
        assert "hyprvolt.db" in names
        files = [m for m in tar.getmembers() if m.isfile() and m.name.startswith("attachments/")]
        assert [tar.extractfile(m).read() for m in files] == [b"config file"]
        tar.extract("hyprvolt.db", tmp_path, filter="data")
    tables = {r[0] for r in sqlite3.connect(tmp_path / "hyprvolt.db").execute("SELECT name FROM sqlite_master")}
    assert {"entities", "attachments", "users"} <= tables


def test_backup_refuses_a_name_it_cannot_tell(app, tmp_path):
    result = app.test_cli_runner().invoke(args=["backup", str(tmp_path / "backup.zip")])
    assert result.exit_code != 0 and ".tar.gz" in result.output


def minimal_pdf(words: str) -> bytes:
    """A one-page PDF with a line of text, written by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({words}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_attachment_contents_are_searchable(app, client, h, admin):
    import io
    server = make(client, h, "server", name="srv1")
    doc = make(client, h, "document", name="Manual")
    client.post(f"/api/entities/{server['id']}/attachments", headers=h, content_type="multipart/form-data",
                data={"file": (io.BytesIO(b"backup target quokkaland on port 873"), "rsyncd.conf")})
    client.post(f"/api/entities/{doc['id']}/attachments", headers=h, content_type="multipart/form-data",
                data={"file": (io.BytesIO(minimal_pdf("Exporter wombat settings")), "guide.pdf",
                               "application/pdf")})
    found = lambda q: [e["name"] for e in client.get(f"/api/entities?q={q}").get_json()["entities"]]
    assert found("quokkaland") == ["srv1"] and found("wombat") == ["Manual"] and found("rsyncd") == ["srv1"]
    # A removed file takes its words with it, and Undo brings them back.
    att = client.get(f"/api/entities/{server['id']}/attachments").get_json()["attachments"][0]
    client.post(f"/api/attachments/{att['id']}/delete", headers=h)
    assert found("quokkaland") == []
    client.post(f"/api/attachments/{att['id']}/restore", headers=h)
    assert found("quokkaland") == ["srv1"]
    # Files attached before search read them are read by the worker.
    from hyprvolt.core.attachments import index_pending
    from hyprvolt.core.models import Attachment
    from hyprvolt.models import db
    with app.app_context():
        Attachment.query.update({"text": None})
        db.session.commit()
        assert index_pending() == 2
        db.session.commit()
    assert found("wombat") == ["Manual"]
    assert "quokkaland" not in client.get("/admin/export.json").data.decode()
