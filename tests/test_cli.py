"""The flask commands an operator runs inside the container."""
import sqlite3


def test_create_user_and_reset_password(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-user", "ops@example.com", "--admin"],
                           input="password1\npassword1\n")
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=["reset-password", "OPS@example.com"],
                           input="password2\npassword2\n")
    assert result.exit_code == 0, result.output
    from hyprprem.models import User
    with app.app_context():
        assert User.query.one().check_password("password2")


def test_create_user_refuses_a_short_password(app):
    result = app.test_cli_runner().invoke(args=["create-user", "a@example.com"],
                                          input="short\nshort\n")
    assert result.exit_code != 0


def test_backup_writes_a_readable_copy(app, tmp_path):
    dest = tmp_path / "copy.db"
    result = app.test_cli_runner().invoke(args=["backup", str(dest)])
    assert result.exit_code == 0, result.output
    tables = {r[0] for r in sqlite3.connect(dest).execute("SELECT name FROM sqlite_master")}
    assert {"users", "items", "settings"} <= tables
