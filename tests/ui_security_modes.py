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
        blank = {'current_provider': '', 'current_model': '', 'providers': []}
        data.update(providers=[{'id': 'test', 'label': 'Test', 'configured': True}], capabilities={
            'chat': {'current_provider': 'test', 'current_model': 'test', 'providers': ['test']},
            'vision': blank, 'image': blank, 'asr': blank,
            'tts': {**blank, 'current_voice': '', 'reply_mode': 'off'},
            'embedding': {**blank, 'current_dim': 0},
            'search': {'strategy': 'auto', 'providers': [], 'fixed_provider': '', 'current_provider': ''},
        })
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
            connections=[
                {'id': 'email', 'name': 'Email', 'connected': True, 'allowed': True, 'scopes': [], 'last_access': None},
                {'id': 'mcp:github', 'name': 'GitHub MCP', 'connected': True, 'allowed': False, 'scopes': ['read'], 'last_access': None},
                {'id': 'github', 'name': 'GitHub', 'connected': False, 'allowed': True, 'scopes': [], 'last_access': None},
            ], secrets=[
                {'name': 'DEEPSEEK_API_KEY', 'source': 'model configuration', 'configured': True},
                {'name': 'CUSTOM:6891955f', 'display_name': 'packyapi',
                 'source': 'custom model provider', 'configured': True},
                {'name': 'CUSTOM:c483bd9c', 'display_name': '灵算',
                 'source': 'custom model provider', 'configured': True},
                {'name': 'CUSTOM:unnamed', 'source': 'custom model provider', 'configured': True},
            ], pending=[], background_tasks=[],
            privacy={'available': True, 'categories': [
                {'id': 'conversations', 'name': {'zh': '对话记录', 'en': 'Conversations'}, 'bytes': 204800,
                 'path': '/isolated/conversations', 'retention': {'zh': '保留至删除', 'en': 'Until deleted'}, 'actions': []},
                {'id': 'activity', 'name': {'zh': '安全活动', 'en': 'Security activity'}, 'bytes': 32768,
                 'path': '/isolated/activity', 'retention': {'zh': '保留至清理', 'en': 'Until cleared'}, 'actions': []},
            ], 'external_transfers': []},
            summary={'status': 'normal', 'app_password_set': False, 'connection_count': 2,
                     'secret_count': 4, 'recent_high_risk': [], 'recent_denials': [],
                     'activity_counts': {'auto_allow': 0, 'user_authorized': 0, 'denied': 0,
                                         'uncertain': False, 'since': 0, 'until': 1},
                     'background_tasks': {'total': 0, 'enabled': 0, 'paused': 0,
                                          'modes': {'read-only': 0, 'workspace-write': 0,
                                                    'full-access': 0, 'custom': 0},
                                          'unknown': 0, 'available': True}},
            project=None, project_policy={}, projects=[], conversation_policy={},
        )
    elif path == '/api/security/confirmations':
        data['pending'] = []
    elif path == '/api/security/activity':
        data['records'] = []
        data['counts'] = {'auto_allow': 0, 'user_authorized': 0, 'denied': 0,
                          'uncertain': False, 'since': 0, 'until': 1}
    elif path == '/api/tools':
        data['tools'] = []
    elif path == '/api/security/privacy':
        data.update(available=True, categories=[], external_transfers=[])
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
        connections_card = page.get_by_role('heading', name='外部连接', exact=True).locator('xpath=..')
        expect(connections_card.get_by_text('2', exact=True)).to_be_visible()
        overview_links = [
            ('默认权限', 'permissions', '默认权限'),
            ('后台任务权限', 'background', '后台任务权限'),
            ('外部连接', 'connections', '连接与访问'),
            ('凭据', 'secrets', '服务凭据'),
            ('安全活动', 'activity', '安全活动'),
            ('数据与隐私', 'privacy', '数据与隐私'),
        ]
        for title, target, destination in overview_links:
            link = page.get_by_role('heading', name=title, exact=True).get_by_role('link', name=title, exact=True)
            expect(link).to_have_attribute('href', '#/security?tab=' + target)
            link.focus()
            link.press('Enter')
            expect(page).to_have_url(url + '/#/security?tab=' + target)
            expect(page.get_by_role('heading', name=destination, exact=True)).to_be_visible()
            if target == 'connections':
                assert page.locator('section h3').all_text_contents() == ['邮箱', 'GitHub MCP', 'GitHub']
            if target == 'secrets':
                page.reload(wait_until='networkidle')
                expect(page.get_by_role('heading', name=destination, exact=True)).to_be_visible()
            page.go_back(wait_until='networkidle')
            expect(page.get_by_role('heading', name='默认权限', exact=True).get_by_role('link')).to_be_visible()
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            page.set_viewport_size({'width': 1280, 'height': 1280})
            page.get_by_role('heading', name='默认权限', exact=True).evaluate("node => node.closest('.overflow-y-auto').scrollTop = 0")
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-overview.png', full_page=True, animations='disabled')
        page.set_viewport_size({'width': 640, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        narrow_title = page.get_by_role('heading', name='默认权限').get_by_role('link')
        expect(narrow_title).to_be_visible()
        assert narrow_title.bounding_box()['height'] <= 44
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-overview-narrow.png', full_page=True, animations='disabled')
        page.set_viewport_size({'width': 1280, 'height': 900})
        expect(page.get_by_text('packyapi', exact=True)).to_be_visible()
        expect(page.get_by_text('灵算', exact=True)).to_be_visible()
        page.get_by_role('navigation', name='安全中心').get_by_role('button', name='权限管理').click()
        default_card = page.get_by_role('heading', name='默认权限').locator('xpath=..')
        expect(default_card).to_be_visible()
        expect(default_card.get_by_role('button', name='只读')).to_be_visible()
        expect(default_card.get_by_role('button', name='自定义')).to_have_count(0)
        before = len(saved)
        default_card.get_by_role('button', name='完全访问').click()
        expect(page.get_by_role('button', name='启用完全访问')).to_have_count(0)
        assert len(saved) > before and saved[-1]['policy']['preset'] == 'full-access'
        assert not any(item.get('policy', {}).get('preset') == 'custom' for item in saved)
        expect(page.get_by_role('heading', name='项目权限')).to_be_visible()
        for tab, heading in [('后台任务权限', '后台任务权限'), ('外部连接', '连接与访问'),
                             ('安全活动', '安全活动'), ('数据与隐私', '数据与隐私')]:
            page.get_by_role('navigation', name='安全中心').get_by_role('button', name=tab, exact=True).click()
            expect(page.get_by_role('heading', name=heading, exact=True)).to_be_visible()
        page.get_by_role('button', name='凭据', exact=True).click()
        expect(page.get_by_text('packyapi', exact=True)).to_be_visible()
        expect(page.get_by_text('灵算', exact=True)).to_be_visible()
        expect(page.get_by_text('自定义厂商', exact=True)).to_be_visible()
        expect(page.get_by_text('CUSTOM:', exact=False)).to_have_count(0)
        expect(page.get_by_role('button', name='删除凭据 CUSTOM:6891955f')).to_have_count(0)
        expect(page.get_by_role('link', name='管理 packyapi')).to_be_visible()
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-credentials.png', full_page=True, animations='disabled')
        page.set_viewport_size({'width': 640, 'height': 900})
        expect(page.get_by_text('packyapi', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-credentials-narrow.png', full_page=True, animations='disabled')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='收起侧栏').click()
        expect(page.get_by_role('complementary')).to_have_css('width', '56px')
        page.get_by_role('navigation', name='安全中心').get_by_role('button', name='总览', exact=True).click()
        mobile_title = page.get_by_role('heading', name='默认权限').get_by_role('link')
        expect(mobile_title).to_be_visible()
        assert mobile_title.bounding_box()['height'] <= 44
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            mobile_title.evaluate("node => node.closest('.overflow-y-auto').scrollTop = 0")
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-overview-mobile.png', full_page=True, animations='disabled')
        page.get_by_role('navigation', name='安全中心').get_by_role('button', name='凭据', exact=True).click()
        expect(page.get_by_text('packyapi', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            page.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-credentials-mobile.png', full_page=True, animations='disabled')
        manage = page.get_by_role('link', name='管理 packyapi')
        manage.focus()
        expect(manage).to_be_focused()
        manage.press('Enter')
        expect(page).to_have_url(url + '/#/settings?tab=models')
        expect(page.get_by_role('heading', name='厂商凭据')).to_be_visible()
        english = browser.new_page(viewport={'width': 1280, 'height': 900})
        english.on('pageerror', lambda error: errors.append(str(error)))
        english.add_init_script("""localStorage.setItem('stella_lang','en');
          localStorage.setItem('cow_theme','dark'); window.electronAPI = {
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        english.route('http://127.0.0.1:9876/**', backend)
        english.goto(url + '/#/security', wait_until='networkidle')
        expect(english.get_by_role('heading', name='Security Center')).to_be_visible()
        expect(english.get_by_role('heading', name='Connections', exact=True).get_by_role('link')).to_have_attribute('href', '#/security?tab=connections')
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            english.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-overview-dark-en.png', full_page=True, animations='disabled')
        english.get_by_role('navigation', name='Security Center').get_by_role('button', name='Credentials', exact=True).click()
        expect(english.get_by_text('packyapi', exact=True)).to_be_visible()
        expect(english.get_by_text('Custom provider', exact=True)).to_be_visible()
        expect(english.get_by_text('CUSTOM:', exact=False)).to_have_count(0)
        if os.environ.get('STELLA_UI_SCREENSHOTS'):
            english.screenshot(path=os.environ['STELLA_UI_SCREENSHOTS'] + '/security-credentials-dark-en.png', full_page=True, animations='disabled')
        assert not errors, errors
        print('Security UI: tabs, presets, provider names, keyboard management link, desktop/narrow/mobile, English dark theme passed')
    finally:
        browser.close()
