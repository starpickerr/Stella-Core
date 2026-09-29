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


@pytest.mark.parametrize("patch_values", [{"host": ""}, {"user": "a\nb"}, {"password": "x\ny"}, {"port": 0}, {"port": 65536}, {"port": 993.5}, {"port": True}])
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
