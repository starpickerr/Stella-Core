"""Credential and mailbox regressions over the plugin's actual SQLite owner."""
import json
import os

import pytest

from stella_email_domain import imap
from stella_email_domain.service import EmailService


@pytest.fixture
def service(tmp_path):
    return EmailService(tmp_path / 'email.db')


def add(service, user='ada@example.com', password='secret', **extra):
    return service.save_account(dict(action='add', host='imap.example.com', user=user,
                                    password=password, **extra))


def test_settings_round_trip_keeps_password_out_of_response(service):
    result = add(service, password=' secret ')
    assert result['configured'] and result['password_set']
    assert 'password' not in result and ' secret ' not in json.dumps(result)
    assert service._account(result['id'])['password'] == ' secret '
    again = service.save_account({'id': result['id'], 'folder': 'Work', 'password': ''})
    assert again['folder'] == 'Work'
    assert service._account(result['id'])['password'] == ' secret '
    reopened = EmailService(service.db_path)
    assert reopened._account(result['id'])['password'] == ' secret '
    if os.name == 'posix':
        assert service.db_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('patch_values', [dict(host=''), dict(user='a\nb'), dict(password='x\ny'),
    dict(port=0), dict(port=65536), dict(port=993.5), dict(port=True), dict(enabled='false'), dict(enabled=0)])
def test_invalid_save_leaves_existing_settings_intact(service, patch_values):
    saved = add(service)
    before = service._load_accounts()
    with pytest.raises(ValueError):
        service.save_account({'id': saved['id'], **patch_values})
    assert service._load_accounts() == before


def test_account_and_folder_have_independent_cursors(service):
    a = add(service)
    b = add(service, folder='Work')
    c = add(service, user='bob@example.com')
    identities = [row['account_id'] for row in service.list_sources()]
    assert len(set(identities)) == 3
    assert service.get_account(a['id'])['source_account_id'] == identities[0]
    assert b['source_account_id'] != c['source_account_id']


def test_saved_settings_are_used_by_email_source(service):
    saved = add(service)
    cfg = service._source(service._account(saved['id']))._settings()
    assert cfg['host'] == 'imap.example.com' and cfg['password'] == 'secret'
    assert cfg['ssl'] is True


@pytest.mark.parametrize('host', ['https://imap.gmail.com', 'imap.gmail.com:993', 'ada@gmail.com',
                                'imap.gmail.com/path', 'imap. gmail.com'])
def test_host_format_error_does_not_overwrite_saved_password(service, host):
    saved = add(service, password='old-secret')
    before = service._load_accounts()
    with pytest.raises(ValueError, match='只填写主机名'):
        service.save_account({'id': saved['id'], 'host': host, 'password': 'replacement'})
    assert service._load_accounts() == before


def test_connection_check_uses_saved_password_without_saving_draft(service, monkeypatch):
    saved = add(service, password='saved-secret')
    before = service._load_accounts()
    checked = []
    monkeypatch.setattr(imap.EmailSource, 'check_connection', lambda src: checked.append(src._settings()))
    service.test_connection({'id': saved['id'], 'host': 'imap.other.example', 'password': '', 'folder': 'Work'})
    assert len(checked) == 1
    assert checked[0]['host'] == 'imap.other.example' and checked[0]['folder'] == 'Work'
    assert checked[0]['user'] == 'ada@example.com' and checked[0]['password'] == 'saved-secret'
    assert service._load_accounts() == before


def test_disabling_mailbox_preserves_credentials_and_source_identity(service):
    first, second = add(service), add(service, user='bob@example.com', password='other')
    identity = service.list_sources()[0]['account_id']
    disabled = service.save_account({'id': first['id'], 'enabled': False})
    assert disabled['configured'] and not disabled['enabled']
    assert len(service.list_accounts()['mailboxes']) == 2
    assert [s['mailbox_id'] for s in service.list_sources()] == [second['id']]
    service.save_account({'id': first['id'], 'folder': 'INBOX'})
    assert not service.get_account(first['id'])['enabled']
    enabled = service.save_account({'id': first['id'], 'enabled': True})
    assert enabled['password_masked'] == '********'
    assert service.list_sources()[0]['account_id'] == identity
    assert service._account(first['id'])['password'] == 'secret'


@pytest.mark.parametrize('saved', [
    dict(host='imap.example.com', user='ada@example.com', password='secret'),
    dict(version=2, mailboxes=[dict(id='old', host='imap.example.com', user='ada@example.com', password='secret')]),
])
def test_existing_mailboxes_default_to_enabled(tmp_path, saved):
    legacy = tmp_path / 'mailbox.json'
    legacy.write_text(json.dumps(saved))
    service = EmailService(tmp_path / 'email.db', legacy_mailbox_path=legacy)
    assert service.list_accounts()['mailboxes'][0]['enabled'] is True
    assert len(service.list_sources()) == 1
    assert json.loads(legacy.read_text()) == saved


def test_accounts_keep_separate_passwords_and_replacements(service):
    first = add(service, password='ada-secret')
    second = add(service, user='bob@example.com', password='bob-secret')
    assert first['id'] != second['id']
    service.save_account({'id': second['id'], 'password': 'new-bob-secret'})
    service.save_account({'id': first['id'], 'password': '********', 'folder': 'Work'})
    rows = service._load_accounts()
    assert rows[0]['password'] == 'ada-secret' and rows[1]['password'] == 'new-bob-secret'
    assert rows[0]['folder'] == 'Work'
    public = service.list_accounts()
    assert all(row['password_masked'] == '********' and row['configured'] for row in public['mailboxes'])
    assert 'secret' not in json.dumps(public)


def test_new_account_cannot_inherit_password_or_save_mask(service):
    add(service, password='ada-secret')
    before = service._load_accounts()
    for password in ('', '********'):
        with pytest.raises(ValueError, match='授权码'):
            add(service, user='bob@example.com', password=password)
        assert service._load_accounts() == before
    with pytest.raises(ValueError, match='邮箱不存在'):
        service.save_account({'id': 'missing', 'password': 'replacement'})
    assert service._load_accounts() == before


def test_duplicate_mailbox_does_not_duplicate_ingestion(service):
    add(service)
    before = service._load_accounts()
    with pytest.raises(ValueError, match='已经添加'):
        add(service)
    assert service._load_accounts() == before
    other = add(service, folder='Work')
    assert other['folder'] == 'Work' and len(service.list_sources()) == 2


def test_legacy_account_migrates_without_resetting_source_identity(tmp_path):
    legacy = tmp_path / 'mailbox.json'
    cfg = dict(host='imap.example.com', user='ada@example.com', password='old-secret', port=993, folder='INBOX')
    legacy.write_text(json.dumps(cfg))
    identity = imap.EmailSource(**cfg).account_id
    service = EmailService(tmp_path / 'email.db', legacy_mailbox_path=legacy)
    assert service.list_accounts()['mailboxes'][0]['id'] == 'legacy'
    add(service, user='bob@example.com', password='bob-secret')
    assert json.loads(legacy.read_text()) == cfg
    assert service._load_accounts()[0]['password'] == 'old-secret'
    assert service.list_sources()[0]['account_id'] == identity
    reopened = EmailService(service.db_path, legacy_mailbox_path=legacy)
    assert len(reopened.list_accounts()['mailboxes']) == 2


def test_delete_all_is_authoritative_even_with_environment_credentials(service, monkeypatch):
    monkeypatch.setenv('IMAP_HOST', 'imap.example.com')
    monkeypatch.setenv('IMAP_USER', 'env@example.com')
    monkeypatch.setenv('IMAP_PASSWORD', 'env-secret')
    assert service._load_accounts()[0]['id'] == 'environment'
    service.delete_account('environment')
    assert service._load_accounts() == []
    assert service.list_accounts()['configured'] is False and service.list_sources() == []
    assert EmailService(service.db_path)._load_accounts() == []


def test_connection_draft_uses_only_the_selected_account(service, monkeypatch):
    add(service, password='ada-secret')
    second = add(service, user='bob@example.com', password='bob-secret')
    before = service._load_accounts()
    checked = []
    monkeypatch.setattr(imap.EmailSource, 'check_connection', lambda src: checked.append(src._settings()))
    service.test_connection({'id': second['id'], 'password': '', 'folder': 'Work'})
    assert checked[0]['user'] == 'bob@example.com' and checked[0]['password'] == 'bob-secret'
    assert checked[0]['folder'] == 'Work' and service._load_accounts() == before


def test_reopening_existing_credentials_database_repairs_overbroad_permissions(service):
    if os.name != 'posix':
        pytest.skip('POSIX credential mode')
    saved = add(service)
    service.db_path.chmod(0o644)
    reopened = EmailService(service.db_path)
    assert service.db_path.stat().st_mode & 0o777 == 0o600
    assert reopened._account(saved['id'])['password'] == 'secret'


def test_reopening_credentials_tightens_live_sqlite_sidecars(service):
    import sqlite3
    if os.name != 'posix':
        pytest.skip('POSIX credential mode')
    saved = add(service)
    with sqlite3.connect(service.db_path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE email_accounts SET password='secret' WHERE id=?", (saved['id'],))
        writer.commit()
        sidecars = [service.db_path.with_name(service.db_path.name + suffix) for suffix in ('-wal', '-shm')]
        assert all(path.exists() for path in sidecars)
        for path in sidecars:
            path.chmod(0o644)
        EmailService(service.db_path)
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in sidecars)
