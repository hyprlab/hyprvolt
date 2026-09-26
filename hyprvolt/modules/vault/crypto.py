"""The vault's key, and encrypting with it.

Values are encrypted with Fernet (AES-128 in CBC mode with an HMAC, from the
``cryptography`` package). The key never goes in the database: it comes from
the ``SECRETS_KEY`` environment variable, or else from ``secrets.key`` in the
data directory, made the first time a secret is saved. A backup of the
database alone can't be read without it, and without it neither can the
instance: losing the key loses the secrets.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

KEY_FILE = "secrets.key"


class Unreadable(Exception):
    """The key in use can't open this value (a different or damaged key)."""


class BadKey(Exception):
    """SECRETS_KEY is set but isn't a key."""


def key_path() -> Path:
    return Path(current_app.config["DATA_DIR"]) / KEY_FILE


def source() -> str:
    """Where the key comes from: "environment", "file", or "none" yet."""
    if os.environ.get("SECRETS_KEY"):
        return "environment"
    return "file" if key_path().exists() else "none"


def _fernet(create: bool = False) -> Fernet | None:
    env = os.environ.get("SECRETS_KEY")
    if env:
        try:
            return Fernet(env.strip().encode())
        except ValueError:
            raise BadKey("SECRETS_KEY is not a key. Make one with `flask secrets new-key`.") from None
    path = key_path()
    if path.exists():
        return Fernet(path.read_bytes().strip())
    if not create:
        return None
    key = Fernet.generate_key()
    # Readable by the app's user only, and never overwritten.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key + b"\n")
    return Fernet(key)


def new_key() -> str:
    return Fernet.generate_key().decode()


def encrypt(text: str) -> str:
    return _fernet(create=True).encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    f = _fernet()
    if f is None:
        raise Unreadable("There is no key to open the secrets with.")
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        raise Unreadable("This secret can't be opened with the key in use.") from None
