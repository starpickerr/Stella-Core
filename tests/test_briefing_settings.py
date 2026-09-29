import json
import os
from unittest.mock import patch

import pytest

from agent.briefing.settings import load_mailbox, save_mailbox
from agent.briefing.sources.email import EmailSource


def test_settings_round_trip_keeps_password_out_of_response(tmp_path):
    path = tmp_path / "briefing" / "mailbox.json"
    result = save_mailbox({"host": "imap.example.com", "user": "ada@example.com", "password": " secret ", "port": 993, "folder": "INBOX"}, path)
    assert result["configured"] is True
    assert result["password_set"] is True
    assert "password" not in result
    assert " secret " not in json.dumps(result)
    assert load_mailbox(path)["password"] == " secret "
    again = save_mailbox({"folder": "Work", "password": ""}, path)
    assert again["folder"] == "Work"
    assert load_mailbox(path)["password"] == " secret "
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("patch_values", [{"host": ""}, {"user": "a\nb"}, {"password": "x\ny"}, {"port": 0}, {"port": 65536}, {"port": 993.5}, {"port": True}, {"enabled": "false"}, {"enabled": 0}])
def test_invalid_save_leaves_existing_settings_intact(tmp_path, patch_values):
    path = tmp_path / "mailbox.json"
    save_mailbox({"host": "imap.example.com", "user": "ada@example.com", "password": "secret"}, path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_mailbox(patch_values, path)
    assert path.read_bytes() == before


def test_account_and_folder_have_independent_cursors():
    first = EmailSource(host="imap.example.com", user="ada@example.com", folder="INBOX")
    second = EmailSource(host="imap.example.com", user="ada@example.com", folder="Work")
    other = EmailSource(host="imap.example.com", user="bob@example.com", folder="INBOX")
    assert len({first.account_id, second.account_id, other.account_id}) == 3
    assert first.account_id == EmailSource(host="imap.example.com", user="ada@example.com", folder="INBOX").account_id


def test_saved_settings_are_used_by_email_source(tmp_path):
    path = tmp_path / "mailbox.json"
    save_mailbox({"host": "imap.example.com", "user": "ada@example.com", "password": "secret"}, path)
    with patch("agent.briefing.settings.mailbox_path", return_value=path):
        settings = EmailSource()._settings()
    assert settings["host"] == "imap.example.com"
    assert settings["password"] == "secret"
    assert settings["ssl"] is True


@pytest.mark.parametrize("host", ["https://imap.gmail.com", "imap.gmail.com:993", "ada@gmail.com", "imap.gmail.com/path", "imap. gmail.com"])
def test_host_format_error_does_not_overwrite_saved_password(tmp_path, host):
    path = tmp_path / "mailbox.json"
    save_mailbox({"host": "imap.gmail.com", "user": "ada@gmail.com", "password": "old-secret"}, path)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="只填写主机名"):
        save_mailbox({"host": host, "password": "replacement"}, path)
    assert path.read_bytes() == original


def test_connection_check_uses_saved_password_without_saving_draft(tmp_path):
    from agent.briefing.settings import check_mailbox_connection
    path = tmp_path / "mailbox.json"
    save_mailbox({"host": "imap.gmail.com", "user": "ada@gmail.com", "password": "saved-secret"}, path)
    original = path.read_bytes()
    with patch("agent.briefing.sources.email.EmailSource") as source:
        check_mailbox_connection({"host": "imap.other.example", "password": "", "folder": "Work"}, path)
    source.assert_called_once_with(host="imap.other.example", user="ada@gmail.com", password="saved-secret", port=993, folder="Work")
    source.return_value.check_connection.assert_called_once_with()
    assert path.read_bytes() == original


def test_disabling_mailbox_preserves_credentials_and_source_identity(tmp_path):
    from agent.briefing.settings import email_sources, public_mailboxes
    path = tmp_path / "mailbox.json"
    first = save_mailbox({"action": "add", "host": "imap.example.com", "user": "ada@example.com", "password": "secret"}, path)
    second = save_mailbox({"action": "add", "host": "imap.example.com", "user": "bob@example.com", "password": "other"}, path)
    identity = email_sources(path)[0].account_id
    disabled = save_mailbox({"id": first["id"], "enabled": False}, path)
    assert disabled["configured"] and not disabled["enabled"]
    assert len(public_mailboxes(path)["mailboxes"]) == 2
    assert [source._settings()["user"] for source in email_sources(path)] == [second["user"]]
    save_mailbox({"id": first["id"], "folder": "INBOX"}, path)
    assert not public_mailboxes(path)["mailboxes"][0]["enabled"]
    enabled = save_mailbox({"id": first["id"], "enabled": True}, path)
    assert enabled["password_masked"] == "********"
    assert email_sources(path)[0].account_id == identity
    assert load_mailbox(path)["password"] == "secret"


@pytest.mark.parametrize("saved", [
    {"host": "imap.example.com", "user": "ada@example.com", "password": "secret"},
    {"version": 2, "mailboxes": [{"id": "old", "host": "imap.example.com", "user": "ada@example.com", "password": "secret"}]},
])
def test_existing_mailboxes_default_to_enabled(tmp_path, saved):
    from agent.briefing.settings import email_sources, public_mailboxes
    path = tmp_path / "mailbox.json"
    path.write_text(json.dumps(saved))
    assert public_mailboxes(path)["mailboxes"][0]["enabled"] is True
    assert len(email_sources(path)) == 1
