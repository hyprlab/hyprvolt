"""Certificates: read from PEM text or from the server that serves them,
kept current by the worker, reminded of, and linked to what they secure."""
import socket
import ssl
import threading
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .conftest import make
from .test_reminders import days, due


def certificate(name="nas1.lab.home", valid_days=90):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=valid_days))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name), x509.DNSName("nas1")]), critical=False)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return cert, pem, key_pem


@pytest.fixture()
def tls_server(tmp_path):
    """A TLS server on a free local port, serving a new certificate to each
    handshake. Yields (port, serve(name, days)) to change what it serves."""
    state = {}
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    stop = threading.Event()

    def serve(name="nas1.lab.home", valid_days=90):
        cert, pem, key_pem = certificate(name, valid_days)
        (tmp_path / "cert.pem").write_text(pem)
        (tmp_path / "key.pem").write_text(key_pem)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
        state["ctx"] = ctx
        return cert

    def loop():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            try:
                with state["ctx"].wrap_socket(conn, server_side=True):
                    pass
            except (OSError, ssl.SSLError):
                conn.close()

    serve()
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield listener.getsockname()[1], serve
    stop.set()
    thread.join(timeout=2)
    listener.close()


def fields(client, entity_id):
    return client.get(f"/api/entities/{entity_id}").get_json()["entity"]["fields"]


def history(client, entity_id):
    return client.get(f"/api/entities/{entity_id}/history").get_json()["history"]


def test_a_certificate_is_read_from_pem_text(client, h, admin):
    cert = make(client, h, "certificate", name="nas1")
    x509cert, pem, key_pem = certificate()
    resp = client.post(f"/certificates/{cert['id']}/read", json={"pem": key_pem + "\n" + pem}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    got = fields(client, cert["id"])
    assert got["names"] == "nas1.lab.home\nnas1" and got["issuer"] == "Self-signed" and got["key_type"] == "ECDSA P-256"
    assert got["expires"] == x509cert.not_valid_after_utc.date().isoformat()
    assert got["fingerprint"] == x509cert.fingerprint(hashes.SHA256()).hex(":").upper()
    assert "PRIVATE" not in str(got) and "BEGIN" not in str(got)
    assert {c["label"] for c in history(client, cert["id"])[0]["changes"]} >= {"Expires", "Issued by", "Names"}
    # The same certificate again changes nothing, so words written by hand stay.
    client.post(f"/api/entities/{cert['id']}", json={"f.issuer": "Synology's own"}, headers=h)
    client.post(f"/certificates/{cert['id']}/read", json={"pem": pem}, headers=h)
    assert fields(client, cert["id"])["issuer"] == "Synology's own"
    bad = client.post(f"/certificates/{cert['id']}/read", json={"pem": "hello"}, headers=h)
    assert bad.status_code == 400 and "BEGIN CERTIFICATE" in bad.get_json()["error"]


def test_the_live_check_reads_what_the_server_serves(app, client, h, admin, tls_server):
    port, serve = tls_server
    cert = make(client, h, "certificate", name="nas1", **{"f.endpoint": f"127.0.0.1:{port}"})
    tab = client.get(f"/e/{cert['id']}/sheet?tab=check").data.decode()
    assert "Not checked yet" in tab
    got = client.post(f"/certificates/{cert['id']}/check", headers=h).get_json()
    assert got["read"] is True
    assert fields(client, cert["id"])["names"] == "nas1.lab.home\nnas1"
    assert "This record matches" in client.get(f"/e/{cert['id']}/sheet?tab=check").data.decode()
    # Renewed on the server: the worker's pass takes the new dates.
    renewed = serve(valid_days=200)
    from hyprvolt.models import db
    from hyprvolt.modules.certificates import views
    from hyprvolt.modules.certificates.models import CertificateDetail
    with app.app_context():
        db.session.get(CertificateDetail, cert["id"]).checked_at = None
        db.session.commit()
        assert views.check_due() == 1
        assert views.check_due() == 0          # checked lately: not again
    assert fields(client, cert["id"])["expires"] == renewed.not_valid_after_utc.date().isoformat()
    assert history(client, cert["id"])[0]["user"] == ""          # the app, not a person


def test_a_failed_check_is_shown_and_filtered(client, h, admin):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]              # nothing listens here once closed
    cert = make(client, h, "certificate", name="gone", **{"f.endpoint": f"127.0.0.1:{port}"})
    got = client.post(f"/certificates/{cert['id']}/check", headers=h).get_json()
    assert got["read"] is False and "Nothing accepts connections" in got["problem"]
    assert "failed" in client.get(f"/e/{cert['id']}/sheet?tab=check").data.decode()
    assert ">gone<" in client.get("/certificates?f=check_failed&view=list").data.decode()
    # A new address clears the old result.
    client.post(f"/api/entities/{cert['id']}", json={"f.endpoint": "gone.lab.home"}, headers=h)
    assert ">gone<" not in client.get("/certificates?f=check_failed&view=list").data.decode()


@pytest.mark.parametrize("endpoint, ok", [
    ("nas1.lab.home", True), ("nas1.lab.home:8443", True), ("https://nas1.lab.home:5001/", True),
    ("[fd00::5]:443", True), ("10.0.20.5", True), ("nas1:99999", False), ("two words", False), ("[nope]:1", False),
])
def test_the_address_to_check_is_checked(client, h, admin, endpoint, ok):
    resp = client.post("/api/entities", json={"type": "certificate", "name": "c", "f.endpoint": endpoint}, headers=h)
    assert (resp.status_code == 200) == ok, resp.get_json()


def test_one_that_renews_itself_is_reminded_of_only_when_late(client, h, admin):
    make(client, h, "certificate", name="manual", **{"f.expires": days(50)})
    auto = make(client, h, "certificate", name="auto", **{"f.expires": days(50), "f.auto_renew": True})
    card = due(client)
    assert ">manual</a>" in card and ">auto</a>" not in card
    client.post(f"/api/entities/{auto['id']}", json={"f.expires": days(10)}, headers=h)
    assert ">auto</a>" in due(client)
    assert ">auto<" in client.get("/certificates?f=expiring&view=list").data.decode()


def test_what_a_certificate_secures_breaks_when_it_expires(client, h, admin):
    service = make(client, h, "service", name="Grafana")
    cert = make(client, h, "certificate", name="*.lab.home", **{"f.secures": service["id"]})
    deps = client.get(f"/api/entities/{cert['id']}/dependencies").get_json()
    assert "Grafana" in str(deps["tree"])
    server = make(client, h, "server", name="srv1")
    assert make(client, h, "certificate", name="srv1.lab.home", **{"f.secures": server["id"]})
    site = make(client, h, "site", name="Home")
    refused = client.post("/api/entities", json={"type": "certificate", "name": "x", "f.secures": site["id"]},
                          headers=h)
    assert refused.status_code == 400


def test_viewers_can_not_check_or_read(client, h, admin, viewer):
    cert = make(client, h, "certificate", name="c", **{"f.endpoint": "127.0.0.1:1"})
    other, vh = viewer
    assert other.post(f"/certificates/{cert['id']}/check", headers=vh).status_code == 403
    assert other.post(f"/certificates/{cert['id']}/read", json={"pem": ""}, headers=vh).status_code == 403
    assert "Check now" not in other.get(f"/e/{cert['id']}/sheet?tab=check").data.decode()
