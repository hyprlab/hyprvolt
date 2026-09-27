"""Reading a certificate, from a server over a TLS handshake or from PEM
text. Only its details are kept: never the certificate, and never a key
pasted along with it.

The handshake trusts nothing and checks nothing, on purpose: it is there to
read what a server presents, self-signed and expired certificates included,
not to decide whether to trust it.
"""
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import NameOID

TIMEOUT = 5
PEM_RE = re.compile(r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----")
HOST_RE = re.compile(r"^(?:\[([0-9A-Fa-f:.]+)\]|([A-Za-z0-9_.-]+))(?::(\d{1,5}))?$")
CURVES = {"secp256r1": "P-256", "secp384r1": "P-384", "secp521r1": "P-521"}


class Unreadable(ValueError):
    """Why a certificate couldn't be read, written for a person."""


def endpoint(text: str) -> tuple[str, int]:
    """The host and port in "host", "host:port", "[fd00::1]:8443" or an
    https:// address. The port is 443 unless given."""
    raw = (text or "").strip()
    if "://" in raw:
        raw = urlsplit(raw).netloc.rsplit("@", 1)[-1]
    m = HOST_RE.match(raw.rstrip("/"))
    port = int(m.group(3) or 443) if m else 0
    if not m or not 1 <= port <= 65535:
        raise Unreadable("Check at must be a host and port, such as nas1.lab.home:443 or [fd00::5]:8443.")
    host = m.group(1) or m.group(2)
    if m.group(1):
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise Unreadable(f"{host} is not an IPv6 address.") from None
    return host, port


def fetch(host: str, port: int, timeout: float = TIMEOUT) -> x509.Certificate:
    """The certificate a server presents on ``host``:``port``."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # Old gear (a printer, a UPS card, an iLO) still speaks old TLS. Nothing
    # is sent but the handshake, so reading its certificate is harmless.
    ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    try:
        ctx.set_ciphers("ALL:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    where = f"{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except socket.gaierror:
        raise Unreadable(f"The name {host} doesn't resolve from the app's server.") from None
    except ConnectionRefusedError:
        raise Unreadable(f"Nothing accepts connections on {where}.") from None
    except (socket.timeout, TimeoutError):
        raise Unreadable(f"{where} didn't answer within {timeout:g} seconds.") from None
    except ssl.SSLError:
        raise Unreadable(f"{where} answered, but not with TLS.") from None
    except OSError as err:
        raise Unreadable(f"{where} can't be reached: {err.strerror or err}.") from None
    if not der:
        raise Unreadable(f"{where} presented no certificate.")
    return x509.load_der_x509_certificate(der)


def read(text: str) -> x509.Certificate:
    """The first certificate in PEM text."""
    m = PEM_RE.search(text or "")
    if not m:
        raise Unreadable("Paste a certificate: the text from -----BEGIN CERTIFICATE----- to "
                         "-----END CERTIFICATE-----.")
    try:
        return x509.load_pem_x509_certificate(m.group(0).encode())
    except ValueError:
        raise Unreadable("That certificate is damaged: part of it may be missing.") from None


def _attr(name: x509.Name, oid) -> str:
    values = name.get_attributes_for_oid(oid)
    return str(values[0].value) if values else ""


def issuer(cert: x509.Certificate) -> str:
    """"Let's Encrypt R11", "Lab Root CA", or "Self-signed"."""
    if cert.issuer == cert.subject:
        return "Self-signed"
    org, cn = _attr(cert.issuer, NameOID.ORGANIZATION_NAME), _attr(cert.issuer, NameOID.COMMON_NAME)
    if org and cn and not cn.lower().startswith(org.split()[0].lower()):
        return f"{org} {cn}"
    return cn or org or cert.issuer.rfc4514_string()


def key_type(cert: x509.Certificate) -> str:
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA {key.key_size}"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return "ECDSA " + CURVES.get(key.curve.name, key.curve.name)
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(key, ed448.Ed448PublicKey):
        return "Ed448"
    if isinstance(key, dsa.DSAPublicKey):
        return f"DSA {key.key_size}"
    return ""


def names(cert: x509.Certificate) -> list[str]:
    """The names it covers: its subject alternative names, led by its common
    name when that isn't among them."""
    out = []
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        out = san.get_values_for_type(x509.DNSName) + [str(a) for a in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        pass
    cn = _attr(cert.subject, NameOID.COMMON_NAME)
    if cn and cn not in out:
        out.insert(0, cn)
    return out


def details(cert: x509.Certificate) -> dict:
    """The certificate's details as the record's field values."""
    return {"names": "\n".join(names(cert)),
            "issuer": issuer(cert)[:200],
            "issued": cert.not_valid_before_utc.date().isoformat(),
            "expires": cert.not_valid_after_utc.date().isoformat(),
            "key_type": key_type(cert),
            "serial": format(cert.serial_number, "X"),
            "fingerprint": cert.fingerprint(hashes.SHA256()).hex(":").upper()}
