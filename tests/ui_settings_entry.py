"""Settings entry, briefing tab, return path, and sidebar footer."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path in ('/api/calendar/apple/status', '/api/todos/apple/status'):
        data['connection'] = dict(supported=False, authorization='unsupported', connected=False,
                                  auto_enabled=False, links=[], calendars=[], lists=[], conflicts=[])
    elif path.startswith('/api/calendar'):
        data.update(events=[], categories=[])
    elif path.startswith('/api/todos'):
        data.update(todos=[], reminders=[], categories=[])
    elif path in ('/api/briefings/elearning', '/api/elearning/file-sync'):
        data['settings'] = {'enabled': False, 'configured': False, 'base_url': '', 'username': '',
                            'courses': [], 'course_options': [], 'account_id': '', 'password_set': False,
                            'password_masked': '', 'file_sync_enabled': False, 'file_sync_root': ''}
    elif path == '/api/briefings/preferences':
        data['preferences'] = {'show_low_priority': True, 'show_ongoing': True, 'important_types': [],
                               'reminder_frequency': 'daily', 'summary_detail': 'brief'}
    elif path.startswith('/api/briefings'):
        data.update(briefings=[], rules=[], default_text='', sources=[], items=[],
                    settings={'mailboxes': []}, actions={}, authorizations=[])
    elif path == '/api/models':
        blank = {'current_provider': '', 'current_model': '', 'providers': []}
        data.update(providers=[{'id': 'test', 'configured': True, 'label': 'Test'}], capabilities={
            'chat': {'current_provider': 'test', 'current_model': 'test', 'providers': ['test']},
            'vision': blank, 'image': blank, 'asr': blank,
            'tts': {'current_provider': '', 'current_model': '', 'providers': [], 'current_voice': '', 'reply_mode': 'off'},
            'embedding': blank,
            'search': {'strategy': 'auto', 'providers': [], 'fixed_provider': '', 'current_provider': ''},
        })
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null,
            getAppVersion: async () => '9.9.9'
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/settings', wait_until='networkidle')

        nav = page.get_by_role('complementary').get_by_role('navigation')
        expect(nav.get_by_role('button', name='设置')).to_be_visible()
        expect(nav.get_by_role('button', name='配置')).to_have_count(0)
        expect(nav.get_by_role('button', name='日志')).to_be_visible()
        expect(page.get_by_role('button', name='更多')).to_have_count(0)
        expect(page.get_by_text('v9.9.9')).to_be_visible()
        page.get_by_role('button', name='收起侧栏').click()
        expect(page.get_by_role('button', name='更多')).to_have_count(0)
        expect(page.get_by_text('v9.9.9')).to_be_visible()
        expect(page.get_by_role('button', name='展开侧栏')).to_be_visible()
        page.get_by_role('button', name='展开侧栏').click()

        nav.get_by_role('button', name='设置').click()
        expect(page.get_by_role('button', name='返回原页面')).to_have_count(0)
        categories = page.get_by_role('navigation', name='设置分类')
        expect(page.get_by_text('颜色模式', exact=True)).to_be_visible()
        expect(page.get_by_text('界面语言', exact=True)).to_be_visible()
        categories.get_by_role('button', name='关于', exact=True).click()
        for label in ('检查更新', '文档中心', 'GitHub', '反馈'):
            expect(page.get_by_text(label, exact=True).first).to_be_visible()

        nav.get_by_role('button', name='简报').click()
        expect(page.get_by_role('button', name='添加邮箱')).to_have_count(0)
        page.get_by_role('button', name='简报设置').click()
        expect(page).to_have_url(test_url + '/#/settings?tab=briefing')
        expect(page.get_by_role('button', name='添加邮箱')).to_be_visible()
        expect(page.get_by_role('button', name='返回简报')).to_have_count(0)
        categories.get_by_role('button', name='模型', exact=True).click()
        page.get_by_role('button', name='返回原页面').click()
        expect(page).to_have_url(test_url + '/#/briefing')

        nav.get_by_role('button', name='日程').click()
        page.get_by_role('button', name='Apple 日历').click()
        page.get_by_role('menuitem', name='管理 Apple 日历').click()
        expect(page.get_by_role('button', name='返回原页面')).to_be_visible()
        page.get_by_role('button', name='返回原页面').click()
        expect(page).to_have_url(test_url + '/#/calendar')

        nav.get_by_role('button', name='事务').click()
        page.get_by_role('button', name='Apple 提醒事项').click()
        page.get_by_role('menuitem', name='管理 Apple 提醒事项').click()
        categories.get_by_role('button', name='简报', exact=True).click()
        page.get_by_role('button', name='返回原页面').click()
        expect(page).to_have_url(test_url + '/#/todos')
        assert errors == [], errors
        print('Settings entry: sidebar, briefing tab, return path, and footer passed')
    finally:
        browser.close()
