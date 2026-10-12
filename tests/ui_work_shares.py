"""File-panel sharing is explicit and recipient-specific in the renderer."""

import json
import os
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
shares = []


def backend(route):
    parsed = urlparse(route.request.url)
    path = parsed.path
    query = parse_qs(parsed.query)
    body = route.request.post_data_json if route.request.method == 'POST' else {}
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/sessions':
        data.update(sessions=[{'session_id': sid, 'title': sid, 'created_at': 1, 'last_active': 1,
                               'msg_count': 1} for sid in ('owner', 'recipient')],
                    total=2, page=1, page_size=50, has_more=False, projects=[])
    elif path == '/api/history':
        data.update(messages=[], total=0, page=1, page_size=20, has_more=False)
    elif path == '/api/projects':
        data.update(current=None, default_workspace='/isolated/work/sessions/default/owner',
                    projects_root='/isolated/projects', recents=[])
    elif path == '/api/workspace/tree':
        sid = query.get('session', ['owner'])[0]
        data.update(path='', root=f'/isolated/work/sessions/default/{sid}', truncated=False,
                    entries=[{'name': 'report.txt', 'path': 'report.txt',
                              'abs_path': '/isolated/work/sessions/default/owner/report.txt',
                              'is_dir': False, 'kind': 'text', 'previewable': True,
                              'size': 6, 'mtime': 1}] if sid == 'owner' else [])
    elif path == '/api/workspace/shares':
        if route.request.method == 'POST':
            assert body['session'] == 'owner' and body['path'] == 'report.txt'
            assert body['recipient'] == 'recipient' and body['access'] == 'write'
            share = {'id': 'share-1', 'path': '/isolated/work/shared/share-1/report.txt',
                     'name': 'report.txt', 'owner_agent': 'default', 'owner_session': 'owner',
                     'recipient_session': 'recipient', 'access': 'write', 'active': True}
            shares.append(share)
            data['share'] = share
        else:
            sid = query.get('session', [''])[0]
            data['shares'] = [row for row in shares if row['owner_session'] == sid or
                              row['active'] and row['recipient_session'] == sid]
    elif path == '/api/workspace/shares/revoke':
        assert body == {'session': 'owner', 'id': 'share-1'}
        shares[0]['active'] = False
        data['share'] = shares[0]
    elif path == '/api/workspace/resolve':
        data['file'] = {'name': 'report.txt', 'path': 'report.txt', 'is_dir': False,
                        'kind': 'text', 'previewable': True, 'size': 6, 'mtime': 1,
                        'abs_path': query['path'][0], 'raw_url': '/api/file?path=report.txt'}
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh');
          localStorage.setItem('cow_session_id','owner'); window.electronAPI = {platform: 'darwin',
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/', wait_until='networkidle')
        page.get_by_title('工作空间').click()
        page.get_by_role('button', name='文件', exact=True).click()
        expect(page.get_by_text('report.txt', exact=True)).to_be_visible()
        page.get_by_role('button', name='共享 report.txt').click()
        page.get_by_label('共享给会话').select_option('recipient')
        page.get_by_label('共享权限').select_option('write')
        page.get_by_role('button', name='确认共享').click()
        expect(page.get_by_text('已共享给 recipient')).to_be_visible()
        assert len(shares) == 1
        page.evaluate("""async () => {
          const { useWorkspaceStore } = await import('/src/store/workspaceStore.ts')
          useWorkspaceStore.getState().onSessionSwitch('recipient')
        }""")
        expect(page.get_by_text('来自 owner')).to_be_visible()
        page.get_by_role('button', name='打开共享文件 report.txt').click()
        expect(page.get_by_text('report.txt', exact=True).first).to_be_visible()
        page.evaluate("""async () => {
          const { useWorkspaceStore } = await import('/src/store/workspaceStore.ts')
          useWorkspaceStore.getState().onSessionSwitch('owner')
        }""")
        page.get_by_role('button', name='文件', exact=True).click()
        page.get_by_role('button', name='撤销共享').click()
        assert shares[0]['active'] is False
        assert errors == [], errors
        print('Work shares UI: exact file, recipient permission, view and revoke passed')
    finally:
        browser.close()
