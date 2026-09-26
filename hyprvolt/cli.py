"""Command-line tools for running an instance.

Inside the container:

    docker exec -it hyprvolt flask create-user you@example.com --admin
    docker exec -it hyprvolt flask reset-password you@example.com
    docker exec hyprvolt flask backup /data/backup-$(date +%F).tar.gz
    docker exec hyprvolt flask turnstile off
    docker exec hyprvolt flask seed-demo

(The image sets FLASK_APP, so no --app is needed inside the container.)

``reset-password`` is the way back in for an admin locked out of the only admin
account; there is no email-based reset, because the app sends no email.
``turnstile off`` is the way back in when a Turnstile widget stops working
(its hostname list changed, Cloudflare is unreachable) and nobody can sign in.
"""
import sqlite3
from pathlib import Path

import click
from flask import Flask, current_app
from flask.cli import with_appcontext
from sqlalchemy import func

from .auth import EMAIL_RE, MIN_PASSWORD
from .models import User, db, set_setting


def register(app: Flask) -> None:
    app.cli.add_command(create_user)
    app.cli.add_command(reset_password)
    app.cli.add_command(backup)
    app.cli.add_command(turnstile)
    app.cli.add_command(seed_demo)
    app.cli.add_command(secrets_group)
    app.cli.add_command(export_json)


def _find(username: str) -> User | None:
    return User.query.filter(func.lower(User.username) == username.strip().lower()).first()


def _ask_password() -> str:
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < MIN_PASSWORD:
        raise click.ClickException(f"Passwords need at least {MIN_PASSWORD} characters.")
    return password


@click.command("create-user")
@with_appcontext
@click.argument("username")
@click.option("--name", default=None, help="Display name.")
@click.option("--role", "role_", type=click.Choice(["viewer", "editor", "admin"]),
              default="viewer", show_default=True, help="What the account may do.")
@click.option("--admin", is_flag=True, help="Shorthand for --role admin.")
@click.option("--secrets", "secrets_", is_flag=True, help="May see and change the secrets vault.")
def create_user(username, name, role_, admin, secrets_):
    """Create an account."""
    username = username.strip().lower()
    if not EMAIL_RE.match(username):
        raise click.ClickException("The username must be an email address.")
    if _find(username):
        raise click.ClickException(f"{username} already exists.")
    role_ = "admin" if admin else role_
    user = User(username=username, name=name, role=role_, can_see_secrets=secrets_)
    user.set_password(_ask_password())
    db.session.add(user)
    db.session.commit()
    click.echo(f"Created {username} ({role_}{', with secrets' if secrets_ else ''}).")


@click.command("reset-password")
@with_appcontext
@click.argument("username")
def reset_password(username):
    """Set a new password for an account."""
    user = _find(username)
    if not user:
        raise click.ClickException(f"No account called {username}.")
    user.set_password(_ask_password())
    db.session.commit()
    click.echo(f"Password updated for {user.username}.")


@click.command("backup")
@with_appcontext
@click.argument("destination", type=click.Path(dir_okay=False, path_type=Path))
def backup(destination: Path):
    """Write a consistent copy of the instance, safe while the app runs.

    A name ending in .tar.gz, .tgz or .tar gets an archive of the database and
    every attachment. A name ending in .db gets the database alone.

    The database copy uses SQLite's online backup API, so a write in progress
    can't leave a torn copy the way copying the file (and its -wal) by hand can.
    """
    import tarfile
    import tempfile

    from .core.attachments import root as attachments_root
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise click.ClickException("backup only knows how to copy a SQLite database.")
    if destination.exists():
        raise click.ClickException(f"{destination} already exists.")
    name = destination.name.lower()
    archive = name.endswith((".tar.gz", ".tgz", ".tar"))
    if not archive and not name.endswith(".db"):
        raise click.ClickException("Name the backup .tar.gz (database and attachments) or .db (database only).")

    def copy_db(target: Path) -> None:
        src = sqlite3.connect(uri.removeprefix("sqlite:///"))
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    files = attachments_root()
    if not archive:
        copy_db(destination)
        if files.is_dir() and any(files.rglob("*")):
            click.echo("Attachments are not in a .db backup; name it .tar.gz to include them.", err=True)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "hyprvolt.db"
            copy_db(db_copy)
            mode = "w" if name.endswith(".tar") else "w:gz"
            with tarfile.open(destination, mode) as tar:
                tar.add(db_copy, arcname="hyprvolt.db")
                if files.is_dir():
                    tar.add(files, arcname="attachments")
    click.echo(f"Backed up to {destination} ({destination.stat().st_size // 1024} KB).")
    from .modules.vault.models import Secret
    if Secret.query.first() is not None:
        click.echo("The secrets key is not in the backup, on purpose. Keep a copy of it separately "
                   "(`flask secrets status` says where it is).")


@click.group("turnstile")
def turnstile():
    """Cloudflare Turnstile on the sign-in and sign-up pages."""


@turnstile.command("status")
@with_appcontext
def turnstile_status():
    """Say whether Turnstile is on, and where its keys come from."""
    from .auth import turnstile_config
    config = turnstile_config()
    if config is None:
        click.echo("Turnstile is off.")
    else:
        click.echo(f"Turnstile is on, site key {config['site_key']}, from the {config['source']}.")


@turnstile.command("off")
@with_appcontext
def turnstile_off():
    """Turn Turnstile off. The saved keys are kept; Settings > Security turns it
    back on after a successful challenge."""
    set_setting("turnstile_enabled", "0")
    click.echo("Turnstile is off. Sign-in and sign-up no longer show a challenge.")


@click.command("seed-demo")
@with_appcontext
@click.option("--force", is_flag=True, help="Add the demo even though the instance has records.")
def seed_demo(force):
    """Fill an empty instance with a small homelab to try the app on."""
    from .demo import DemoError, seed
    try:
        made = seed(force=force)
    except DemoError as err:
        raise click.ClickException(str(err) + " Use --force to add it anyway.") from None
    click.echo(f"Added the demo homelab: {made} records.")


@click.group("secrets")
def secrets_group():
    """The secrets vault's key."""


@secrets_group.command("status")
@with_appcontext
def secrets_status():
    """Say where the key is and whether it opens the secrets."""
    from .modules.vault import crypto
    from .modules.vault.models import Secret
    try:
        source = crypto.source()
        where = {"environment": "the SECRETS_KEY environment variable",
                 "file": str(crypto.key_path()),
                 "none": f"not made yet; it will be {crypto.key_path()}"}[source]
    except crypto.BadKey as err:
        raise click.ClickException(str(err)) from None
    secrets_ = Secret.query.filter_by(deleted_at=None).all()
    click.echo(f"Key: {where}")
    click.echo(f"Secrets: {len(secrets_)}")
    unreadable = 0
    for s in secrets_:
        try:
            crypto.decrypt(s.ciphertext)
        except (crypto.Unreadable, crypto.BadKey):
            unreadable += 1
    if unreadable:
        raise click.ClickException(f"{unreadable} of them can't be opened with this key.")
    if secrets_:
        click.echo("The key opens all of them. Keep a copy of it away from this server: without it they are lost.")


@secrets_group.command("new-key")
def secrets_new_key():
    """Print a new key, for SECRETS_KEY on a fresh instance."""
    from .modules.vault import crypto
    click.echo(crypto.new_key())


@click.command("export")
@with_appcontext
@click.argument("destination", type=click.Path(dir_okay=False, path_type=Path))
def export_json(destination: Path):
    """Write the whole instance as JSON, as Settings > Admin does: no
    password hashes, secret values, token hashes or files."""
    import json

    from .core.transfer import export_all
    if destination.exists():
        raise click.ClickException(f"{destination} already exists.")
    data = export_all()
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    rows = sum(len(t) for t in data["tables"].values())
    click.echo(f"Exported {rows} rows from {len(data['tables'])} tables to {destination}.")
