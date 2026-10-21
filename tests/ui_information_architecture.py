"""Settings categories, legacy tab links, appearance controls, and the About page."""

import json
import os
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5184')
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
    elif path == '/api/plugins/runtime':
        data['plugins'] = [{'pluginId': 'stella.tasks', 'name': '事务', 'version': '1.0.0',
                            'firstParty': True, 'intent': 'enabled', 'state': 'ready'}]
    elif path in ('/api/plugins/settings', '/api/plugins/authorization'):
        data['result'] = []
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
        page = browser.new_page(viewport={'width': 1280, 'height': 960})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {platform: 'darwin',
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null,
            getAppVersion: async () => '9.9.9', checkForUpdate: () => {},
            getLoginItemEnabled: async () => false, setLoginItemEnabled: async enabled => ({ok:true, enabled})
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/settings', wait_until='networkidle')
        expect(page).to_have_url(test_url + '/#/general')
        expect(page.get_by_role('heading', name='通用', exact=True)).to_be_visible()
        expect(page.get_by_role('navigation', name='设置分类')).to_have_count(0)
        for text in ('界面语言', '任务通知', '版本 9.9.9'):
            expect(page.get_by_text(text, exact=True)).to_be_visible()
        expect(page.get_by_text('访问密码', exact=True)).to_have_count(0)
        appearance = page.get_by_role('radiogroup', name='颜色模式')
        appearance.get_by_role('radio', name='深色', exact=True).click()
        expect(page.locator('html')).to_have_class(re.compile(r'\bdark\b'))
        appearance.get_by_role('radio', name='浅色', exact=True).click()
        expect(page.get_by_role('radiogroup', name='主题').get_by_role('radio', name='Meadow')).to_be_checked()
        page.get_by_role('switch', name='开机自启').check()
        expect(page.get_by_role('switch', name='开机自启')).to_be_checked()
        expect(page.get_by_role('button', name='检查更新', exact=True)).to_be_visible()
        info = page.get_by_test_id('nav-group-info')
        for text in ('数据', '知识', '记忆'):
            expect(info.get_by_role('button', name=text, exact=True)).to_be_visible()
        system = page.get_by_test_id('nav-group-system')
        for text in ('模型', 'Agent 配置', '能力', '安全', '通用', '日志'):
            expect(system.get_by_role('button', name=text, exact=True)).to_be_visible()
        expect(page.get_by_role('complementary').get_by_role('button', name='日志', exact=True)).to_have_count(1)
        logs = system.get_by_role('button', name='日志', exact=True)
        logs.focus()
        expect(logs).to_be_focused()
        logs.press('Enter')
        expect(page).to_have_url(test_url + '/#/logs')
        expect(logs).to_have_class(re.compile('bg-accent-soft'))
        expect(page.get_by_role('heading', name='日志', exact=True)).to_be_visible()
        page.screenshot(path='/tmp/stella-logs-system-nav-desktop.png', full_page=True)
        system.get_by_role('button', name='模型', exact=True).click()
        expect(page).to_have_url(test_url + '/#/models')
        expect(page.get_by_role('heading', name='模型', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Agent 菜单', exact=True)).to_have_count(0)
        agent_config = system.get_by_role('button', name='Agent 配置', exact=True)
        agent_config.focus()
        expect(agent_config).to_be_focused()
        agent_config.press('Enter')
        expect(agent_config).to_have_class(re.compile('bg-accent-soft'))
        expect(page).to_have_url(test_url + '/#/agent-settings')
        expect(page.get_by_label('最大执行步数')).to_have_value('8')
        page.get_by_role('switch', name='深度思考').click()
        page.get_by_role('button', name='保存助手设置').click()
        expect(page.get_by_text('已保存', exact=True)).to_be_visible()
        assert saved[-1]['enable_thinking'] is True
        redirects = {'models': '/models', 'assistant': '/agent-settings', 'plugins': '/skills?tab=plugins&view=settings',
                     'about': '/general?section=about', 'basic': '/general',
                     'integrations&section=apple-calendar': '/calendar/settings/apple'}
        for old, new in redirects.items():
            page.goto(test_url + '/#/settings?tab=' + old, wait_until='networkidle')
            expect(page).to_have_url(test_url + '/#' + new)
        page.goto(test_url + '/#/skills?tab=plugins&view=settings&plugin=stella.tasks', wait_until='networkidle')
        expect(page.get_by_role('link', name='管理插件授权', exact=True)).to_have_attribute('href', '#/security?tab=plugins&plugin=stella.tasks')
        expect(page.get_by_role('button', name='权限与授权', exact=True)).to_have_count(0)
        expect(page.get_by_role('link', name='打开事务页面', exact=True)).to_be_visible()
        page.goto(test_url + '/#/general', wait_until='networkidle')
        page.set_viewport_size({'width': 640, 'height': 920})
        expect(page.get_by_role('button', name='检查更新', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path='/tmp/stella-general-narrow.png', full_page=True)
        page.get_by_role('button', name='收起侧栏', exact=True).click()
        compact_agent = system.get_by_role('button', name='Agent 配置', exact=True)
        expect(compact_agent).to_be_visible()
        compact_agent.click()
        expect(page).to_have_url(test_url + '/#/agent-settings')
        expect(page.get_by_role('heading', name='Agent 配置', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='Agent 菜单', exact=True)).to_have_count(0)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path='/tmp/stella-agent-system-nav-narrow.png', full_page=True)
        compact_logs = system.get_by_role('button', name='日志', exact=True)
        expect(compact_logs).to_be_visible()
        compact_logs.click()
        expect(page).to_have_url(test_url + '/#/logs')
        expect(compact_logs).to_have_class(re.compile('bg-accent-soft'))
        expect(page.get_by_role('heading', name='日志', exact=True)).to_be_visible()
        page.screenshot(path='/tmp/stella-logs-system-nav-narrow.png', full_page=True)
        assert errors == [], errors
        print('PASS: configuration ownership, Agent configuration in System, sidebar groups, legacy redirects, General/About and narrow layout')
    finally:
        browser.close()
