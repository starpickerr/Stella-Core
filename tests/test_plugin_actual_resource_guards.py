"""Actual reads recheck the Core-bound scope against the configuration they use."""
from pathlib import Path

from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


def test_actual_email_folder_change_cannot_expand_a_resolved_scope(tmp_path):
    session = PluginSession(Path('stella-plugins-workspace/plugins/email'), source_label='guard', registry=PluginRegistry())
    handle = {'namespace':'stella.email', 'dbPath':str(tmp_path / 'email.sqlite')}
    try:
        session.start()
        account = session.invoke('save_account', {'payload':{'enabled':True,'host':'imap.example.com','user':'alice@example.com',
            'password':'test-only','port':993,'folder':'School'}, '_dataHandle':handle})['value']
        scope = [{'kind':'folder', 'id':account['source_account_id']}]
        updated = session.invoke('save_account', {'payload':{'id':account['id'],'folder':'Private'}, '_dataHandle':handle})
        assert updated['status'] == 'succeeded'
        result = session.invoke('fetch_messages', {'account_id':account['id'], '_dataHandle':{**handle, 'authorizedResources':scope}})
        assert result['status'] == 'failed' and result['error']['code'] == 'permission_denied'
        assert result['sideEffects'] == 'none'
    finally:
        session.dispose()


def test_actual_elearning_account_change_cannot_reuse_numeric_course_scope(tmp_path):
    session = PluginSession(Path('stella-plugins-workspace/plugins/elearning'), source_label='guard', registry=PluginRegistry())
    handle = {'namespace':'stella.elearning', 'dataDir':str(tmp_path / 'elearning')}
    try:
        session.start()
        payload = {'enabled':True,'base_url':'https://canvas.example.com','username':'alice','password':'test-only','courses':['1']}
        saved = session.invoke('save_settings', {'payload':payload, '_dataHandle':handle})
        assert saved['status'] == 'succeeded', saved
        scope = [{'kind':'course', 'id':saved['value']['account_id'] + ':1'}]
        assert session.invoke('save_settings', {'payload':{**payload, 'username':'bob'}, '_dataHandle':handle})['status'] == 'succeeded'
        result = session.invoke('fetch_source', {'_dataHandle':{**handle, 'authorizedResources':scope}})
        assert result['status'] == 'failed' and result['error']['code'] == 'permission_denied'
        assert result['sideEffects'] == 'none'
    finally:
        session.dispose()
