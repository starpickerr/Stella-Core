"""Security Center shows product modes and Full Access limits."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
DEFINITIONS = [
    {'id': 'read-only', 'name': {'zh': '只读', 'en': 'Read Only'},
     'description': {'zh': '读取', 'en': 'Read'}, 'rules': {}},
    {'id': 'workspace-write', 'name': {'zh': '工作区写入', 'en': 'Workspace Write'},
     'description': {'zh': '写入', 'en': 'Write'}, 'rules': {}},
    {'id': 'full-access', 'name': {'zh': '完全访问', 'en': 'Full Access'},
     'description': {'zh': '放宽', 'en': 'Relax'}, 'rules': {}},
    {'id': 'custom', 'name': {'zh': '自定义', 'en': 'Custom'},
     'description': {'zh': '调整', 'en': 'Adjust'}, 'rules': {}},
]


saved = []


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if route.request.method == 'POST' and path == '/api/security/policy':
        saved.append(json.loads(route.request.post_data or '{}'))
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path in ('/api/sessions', '/api/history', '/api/projects'):
        data.update(sessions=[], history=[], messages=[], total=0, page=1, page_size=20,
                    has_more=False, projects=[], current=None)
    elif path == '/api/security/center':
        data.update(
            global_policy={'preset': 'workspace-write', 'rules': {}, 'connections': {}},
            effective_policy={'preset': 'workspace-write', 'rules': {}, 'connections': {}},
            effective_mode='workspace-write', effective_rules={}, policy_source='global',
            mode_definitions=DEFINITIONS, authorized_roots=['/isolated/work'],
            process_isolation={'status': 'enabled', 'reason': 'Seatbelt is active. 完全访问仍拦截其他会话的私有工作区。'},
            connections=[], secrets=[], pending=[],
            summary={'status': 'normal', 'app_password_set': False, 'connection_count': 0,
                     'secret_count': 0, 'recent_high_risk': [], 'recent_denials': []},
            project=None, project_policy={}, projects=[], conversation_policy={},
        )
    elif path == '/api/security/confirmations':
        data['pending'] = []
    elif path == '/api/security/activity':
        data['records'] = []
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true',
                           'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                           'Access-Control-Allow-Headers': 'Content-Type'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh');
          window.electronAPI = {
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/security', wait_until='networkidle')
        expect(page.get_by_role('heading', name='安全中心')).to_be_visible()
        expect(page.get_by_text('工作区写入', exact=True).first).to_be_visible()
        page.get_by_role('button', name='默认权限').click()
        expect(page.get_by_role('button', name='只读')).to_be_visible()
        page.get_by_role('button', name='完全访问').click()
        expect(page.get_by_role('button', name='启用完全访问')).to_have_count(0)
        expect(page.get_by_text('破坏性操作仍需审批')).to_have_count(0)
        assert saved and saved[-1]['policy']['preset'] == 'full-access'
        page.get_by_role('button', name='自定义').click()
        expect(page.get_by_role('heading', name='逐项调整权限')).to_be_visible()
        expect(page.get_by_role('button', name='保存自定义')).to_be_visible()
        assert saved[-1]['policy']['preset'] == 'custom'
        assert not errors, errors
        print('Security modes UI: immediate Full Access and on-page custom editor passed')
    finally:
        browser.close()
