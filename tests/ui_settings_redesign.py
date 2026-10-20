"""Settings categories, legacy tab links, appearance controls, and the About page."""

import json
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
saved = []


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
    elif path in ('/api/calendar/categories', '/api/todos/categories'):
        data['categories'] = []
    elif path == '/config':
        if route.request.method == 'POST':
            saved.append(json.loads(route.request.post_data or '{}').get('updates', {}))
        data.update(model='test-model', bot_type='test', providers={'test': {'label': 'Test', 'models': ['test-model']}},
                    api_keys={}, agent_max_context_tokens=50000, agent_max_context_turns=12, agent_max_steps=8,
                    enable_thinking=False, subagent_enabled=True, self_evolution_enabled=False, web_password_masked='')
    elif path == '/api/elearning/file-sync':
        data['settings'] = {'enabled': False, 'configured': False, 'base_url': '', 'username': '',
                            'courses': [], 'course_options': [], 'account_id': '', 'password_set': False,
                            'password_masked': '', 'file_sync_root': ''}
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
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {platform: 'darwin',
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null,
            getAppVersion: async () => '9.9.9', checkForUpdate: () => {}
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/settings', wait_until='networkidle')

        categories = page.get_by_role('navigation', name='设置分类')
        names = [item.inner_text().strip() for item in categories.get_by_role('button').all()]
        assert names == ['通用', '模型', '助手', '连接', '插件', '关于'], names
        expect(categories.get_by_role('button', name='通用', exact=True)).to_have_attribute('aria-current', 'page')

        main = page.locator('[data-settings-content]')
        expect(main.get_by_role('heading', name='通用', exact=True)).to_be_visible()
        appearance = main.get_by_role('radiogroup', name='颜色模式')
        for label in ('浅色', '深色', '跟随系统'):
            expect(appearance.get_by_role('radio', name=label, exact=True)).to_be_visible()
        appearance.get_by_role('radio', name='深色', exact=True).click()
        expect(page.locator('html')).to_have_class(re.compile(r'\bdark\b'))
        expect(main.get_by_role('radiogroup', name='主题').get_by_role('radio', name='Meadow')).to_be_checked()
        expect(main.get_by_text('界面语言', exact=True)).to_be_visible()
        expect(main.get_by_text('访问密码', exact=True)).to_be_visible()

        categories.get_by_role('button', name='助手', exact=True).click()
        expect(page).to_have_url(test_url + '/#/settings?tab=assistant')
        expect(main.get_by_role('heading', name='助手', exact=True)).to_be_visible()
        expect(main.get_by_label('最大执行步数')).to_have_value('8')
        main.get_by_role('switch', name='深度思考').click()
        main.get_by_role('button', name='保存助手设置').click()
        expect(main.get_by_text('已保存')).to_be_visible()
        assert saved and saved[-1]['enable_thinking'] is True and saved[-1]['agent_max_steps'] == 8, saved

        categories.get_by_role('button', name='关于', exact=True).click()
        expect(main.get_by_text('版本 9.9.9')).to_be_visible()
        expect(main.get_by_role('button', name='检查更新')).to_be_visible()
        for label, hint in (('文档中心', '功能说明和配置指南'), ('GitHub', '源代码和版本发布'), ('反馈', '报告问题或提出建议')):
            expect(main.get_by_role('button', name=label)).to_be_visible()
            expect(main.get_by_text(hint)).to_be_visible()
        expect(main.get_by_text('主题', exact=True)).to_have_count(0)
        expect(main.get_by_text('语言', exact=True)).to_have_count(0)

        page.goto(test_url + '/#/settings?tab=basic', wait_until='networkidle')
        expect(categories.get_by_role('button', name='通用', exact=True)).to_have_attribute('aria-current', 'page')
        page.goto(test_url + '/#/settings?tab=integrations&section=apple-calendar', wait_until='networkidle')
        expect(categories.get_by_role('button', name='连接', exact=True)).to_have_attribute('aria-current', 'page')

        page.set_viewport_size({'width': 760, 'height': 900})
        overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        assert not overflow, 'settings scroll horizontally at narrow width'
        assert errors == [], errors
        print('Settings redesign: categories, appearance, assistant save, and About passed')
    finally:
        browser.close()
