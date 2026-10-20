"""Capabilities page: horizontal tabs, concise cards, skill toggle, and load errors."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
request_counts = {}
fail_tools = [False]
fail_mcp = [False]
empty_mcp = [False]
plugin_enabled = [True]
plugin_posts = []
skill_posts = []
hold_skill = [False]
pending_skill_routes = []
plan_requests = []
updated = [False]
fail_update = [False]
fail_plan = [False]
INTRO = '检索 Agent 的长期记忆；启用知识库时也可检索知识内容。这份介绍需要完整显示，不能被两行省略号截断。'
DETAIL = '只在带有记忆能力的对话中可用。它可以查找记忆和已启用的知识内容。'


def backend(route):
    path = urlparse(route.request.url).path
    request_counts[path] = request_counts.get(path, 0) + 1
    method = route.request.method
    body = route.request.post_data_json if method == 'POST' else {}
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True, 'label': 'Test'}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/tools':
        if fail_tools[0]:
            data = {'status': 'error', 'message': '工具目录加载失败'}
        else:
            data['tools'] = [{
                'id': 'read',
                'title': {'zh': '读取文件', 'en': 'Read Files'},
                'intro': {'zh': '读取工作区中的文件内容。', 'en': 'Read workspace files.'},
                'detail': {'zh': '只能读取当前工作区里已有的文件。', 'en': 'Reads files in the workspace.'},
                'available': True,
                'reason': {'zh': '', 'en': ''},
            }, {
                'id': 'memory_search',
                'title': {'zh': '搜索记忆', 'en': 'Search Memory'},
                'intro': {'zh': INTRO, 'en': 'Search the agent memory. This introduction must stay complete.'},
                'detail': {'zh': DETAIL, 'en': 'Available only in a conversation with memory.'},
                'available': False,
                'reason': {'zh': '仅在启用记忆的对话中可用。', 'en': 'Available only in a conversation with memory.'},
            }]
    elif path == '/api/briefings/elearning':
        data['settings'] = {'enabled': False, 'configured': False, 'base_url': '', 'username': '',
                            'courses': [], 'course_options': [], 'account_id': '', 'password_set': False,
                            'password_masked': '', 'file_sync_enabled': False, 'file_sync_root': ''}
    elif path == '/api/briefings/preferences':
        data['preferences'] = {'show_low_priority': True, 'show_ongoing': True, 'important_types': [],
                               'reminder_frequency': 'daily', 'summary_detail': 'brief'}
    elif path == '/api/email/accounts' or path.startswith('/api/briefings'):
        data.update(rules=[], default_text='', sources=[], items=[], settings={'mailboxes': []},
                    actions={}, authorizations=[])
    elif path == '/api/mcp' and fail_mcp[0]:
        data = {'status': 'error', 'message': 'MCP 目录加载失败'}
    elif path == '/api/mcp' and empty_mcp[0]:
        data['servers'] = []
    elif path == '/api/mcp':
        data['servers'] = [{'name': 'Documents', 'transport': 'stdio', 'state': 'ready',
                            'tools': [{'name': 'search_docs', 'description': '搜索文档内容'}]},
                           {'name': 'Offline', 'transport': 'sse', 'state': 'failed', 'tools': []}]
    elif path == '/api/plugins/manage':
        plugin_posts.append(body)
        if body['action'] == 'update':
            if fail_update[0]:
                data = {'status': 'error', 'message': '更新失败，请重试'}
            else:
                updated[0] = True
        else:
            plugin_enabled[0] = body['action'] == 'enable'
        data['result'] = {}
    elif path == '/api/plugins/runtime':
        data['plugins'] = [{'pluginId': 'stella.briefing', 'userId': 'test', 'name': '简报',
                            'version': '1.0.0', 'intent': 'enabled' if plugin_enabled[0] else 'disabled', 'state': 'stopped',
                            'sourceLabel': 'official', 'generation': 1, 'services': []}]
    elif path == '/api/plugins/dual-update-plan':
        plan_requests.append(path)
        if fail_plan[0]:
            data = {'status': 'error', 'message': '更新目录加载失败'}
        else:
            data.update(core={'from': '1.0'}, updates=[] if updated[0] else [
                {'pluginId': 'stella.briefing', 'fromVersion': '1.0.0', 'toVersion': '1.1.0'},
                {'pluginId': 'stella.blocked', 'fromVersion': '1.0.0', 'toVersion': '2.0.0'}],
                blocked=[{'pluginId': 'stella.blocked', 'reason': '需要更新 Core'}])
    elif path == '/api/plugins/settings':
        data['result'] = []
    elif path == '/api/plugins/authorization':
        data['result'] = []
    elif path == '/api/skills' and method == 'POST':
        skill_posts.append(body)
        if hold_skill[0]:
            pending_skill_routes.append(route)
            return
    elif path == '/api/skills':
        data['skills'] = [{
            'name': 'demo-skill', 'display_name': '演示技能', 'enabled': True, 'source': 'custom',
            'description': '技能介绍需要完整显示。' * 8,
        }, {
            'name': 'short-skill', 'display_name': '短技能', 'enabled': True, 'source': 'custom',
            'description': '一行介绍。',
        }, {
            'name': 'mid-skill', 'display_name': '中技能', 'enabled': True, 'source': 'custom',
            'description': '中等长度的介绍。' * 2,
        }, {
            'name': 'tiny-skill', 'display_name': '更短技能', 'enabled': True, 'source': 'custom',
            'description': '短。',
        }]
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {platform: 'darwin',
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/skills', wait_until='networkidle')
        nav = page.get_by_role('navigation')
        expect(nav.get_by_role('button', name='能力', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='能力', exact=True)).to_be_visible()
        expect(nav.get_by_role('button', name='插件', exact=True)).to_have_count(0)
        expect(page.get_by_role('tab')).to_have_text(['插件', '工具', '技能', 'MCP'])
        expect(page.get_by_role('tab', name='插件', exact=True)).to_have_attribute('aria-selected', 'true')
        expect(page.get_by_role('article', name='read')).to_have_count(0)
        expect(page.get_by_role('article', name='简报')).to_be_visible()
        panel = page.get_by_role('tabpanel')
        heading_box = panel.get_by_role('heading', name='插件', exact=True).bounding_box()
        refresh_box = panel.get_by_role('button', name='刷新', exact=True).bounding_box()
        plugin_box = page.get_by_role('article', name='简报').bounding_box()
        assert abs(heading_box['y'] + heading_box['height'] / 2 - refresh_box['y'] - refresh_box['height'] / 2) < 2, (heading_box, refresh_box)
        assert 8 <= plugin_box['y'] - refresh_box['y'] - refresh_box['height'] <= 16, (plugin_box, refresh_box)
        for text in ['查看插件并管理启用状态', '停用和卸载保留业务数据。插件启用后，会在首次获准调用时启动。']:
            expect(page.get_by_text(text, exact=True)).to_have_count(0)
        for tab, endpoint in [('插件', '/api/plugins/runtime'), ('工具', '/api/tools'), ('技能', '/api/skills'), ('MCP', '/api/mcp')]:
            page.get_by_role('tab', name=tab, exact=True).click()
            refresh = page.get_by_role('tabpanel').get_by_role('button', name='刷新', exact=True)
            expect(refresh).to_be_enabled()
            before = request_counts.get(endpoint, 0)
            refresh.click()
            expect(refresh).to_be_enabled()
            assert request_counts[endpoint] == before + 1, (tab, request_counts)
            expect(page.get_by_role('tab', name=tab, exact=True)).to_have_attribute('aria-selected', 'true')
        expect(page.get_by_text('已配置的 MCP 服务及其运行时工具。修改连接配置后，服务会在 Agent 加载时更新。', exact=True)).to_have_count(0)
        page.get_by_role('tab', name='MCP', exact=True).click()
        mcp = page.get_by_role('article', name='Documents')
        expect(mcp.get_by_text('已连接')).to_be_visible()
        mcp.get_by_role('button', name='工具').click()
        expect(mcp.get_by_text('search_docs', exact=True)).to_be_visible()
        expect(mcp.get_by_text('搜索文档内容')).to_be_visible()
        page.get_by_role('tab', name='工具', exact=True).click()
        memory = page.get_by_role('article', name='memory_search')
        expect(memory.get_by_role('heading', name='memory_search', exact=True)).to_be_visible()
        expect(memory.get_by_text(INTRO)).to_be_visible()
        expect(memory.get_by_text('不可用', exact=True)).to_be_visible()
        expect(page.get_by_role('article', name='read').get_by_text('可用', exact=True)).to_be_visible()
        expect(memory.get_by_role('switch')).to_have_count(0)
        expect(page.get_by_text('搜索记忆', exact=True)).to_have_count(0)
        expect(page.get_by_text('读取文件', exact=True)).to_have_count(0)
        expect(page.get_by_text('查看详情')).to_have_count(0)
        expect(page.locator('.line-clamp-2')).to_have_count(0)
        read_box = page.get_by_role('article', name='read').bounding_box()
        memory_box = memory.bounding_box()
        assert abs(read_box['y'] - memory_box['y']) < 2 and memory_box['x'] > read_box['x'] + read_box['width'], (read_box, memory_box)

        expect(memory.get_by_text(DETAIL)).to_have_count(0)
        expect(memory.get_by_role('button', name='适用说明')).to_have_count(0)
        assert skill_posts == []

        page.goto(test_url + '/#/skills/tools/memory_search', wait_until='networkidle')
        expect(page).to_have_url(test_url + '/#/skills')

        page.get_by_role('tab', name='技能', exact=True).click()
        demo = page.get_by_role('article', name='演示技能')
        short = page.get_by_role('article', name='短技能', exact=True)
        mid = page.get_by_role('article', name='中技能', exact=True)
        tiny = page.get_by_role('article', name='更短技能', exact=True)
        expect(demo.get_by_text('技能介绍需要完整显示。', exact=False)).to_be_visible()
        demo_box, short_box, mid_box, tiny_box = demo.bounding_box(), short.bounding_box(), mid.bounding_box(), tiny.bounding_box()
        assert short_box['height'] + 20 < demo_box['height'], (demo_box, short_box)
        assert abs(demo_box['y'] - short_box['y']) < 2 and short_box['x'] > demo_box['x'], (demo_box, short_box)
        left_gap = mid_box['y'] - (demo_box['y'] + demo_box['height'])
        right_gap = tiny_box['y'] - (short_box['y'] + short_box['height'])
        assert abs(left_gap - right_gap) < 2 and 8 <= left_gap <= 16, (left_gap, right_gap, demo_box, short_box, mid_box, tiny_box)
        assert skill_posts == []
        hold_skill[0] = True
        demo.get_by_role('switch').click()
        expect(page.get_by_role('tabpanel').get_by_role('button', name='刷新', exact=True)).to_be_disabled()
        expect(demo.get_by_role('switch')).to_be_disabled()
        assert pending_skill_routes
        pending_skill_routes.pop().fulfill(status=200, content_type='application/json', body=json.dumps({'status': 'success'}),
            headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})
        hold_skill[0] = False
        expect(page.get_by_role('tabpanel').get_by_role('button', name='刷新', exact=True)).to_be_enabled()
        expect(demo.get_by_role('switch')).not_to_be_checked()
        assert skill_posts and skill_posts[-1]['action'] == 'close'
        assert skill_posts[-1]['name'] == 'demo-skill'

        page.get_by_role('tab', name='插件', exact=True).click()
        plugin = page.get_by_role('article', name='简报')
        plugin.get_by_role('button', name='停用', exact=True).click()
        expect(plugin.get_by_role('button', name='启用', exact=True)).to_be_visible()
        assert plugin_posts[-1] == {'action': 'disable', 'pluginId': 'stella.briefing'}
        plugin.get_by_role('button', name='启用', exact=True).click()
        expect(plugin.get_by_role('button', name='停用', exact=True)).to_be_visible()
        page.get_by_role('tab', name='MCP', exact=True).click()
        mcp_section = page.locator('section').filter(has=page.get_by_role('heading', name='MCP', exact=True))
        fail_mcp[0] = True
        mcp_section.get_by_role('button', name='刷新', exact=True).click()
        expect(mcp_section.get_by_role('alert')).to_contain_text('MCP 目录加载失败')
        fail_mcp[0] = False
        mcp_section.get_by_role('button', name='重试', exact=True).click()
        expect(page.get_by_role('article', name='Documents')).to_be_visible()
        empty_mcp[0] = True
        mcp_section.get_by_role('button', name='刷新', exact=True).click()
        expect(mcp_section.get_by_text('暂无 MCP 服务', exact=True)).to_be_visible()
        expect(page.get_by_text('尚未配置 MCP 服务。可在工作区的 mcp.json 中添加服务。', exact=True)).to_have_count(0)
        empty_mcp[0] = False
        mcp_section.get_by_role('button', name='刷新', exact=True).click()
        expect(page.get_by_role('article', name='Documents')).to_be_visible()
        page.get_by_role('heading', name='MCP', exact=True).scroll_into_view_if_needed()
        page.screenshot(path='/tmp/stella-capabilities-mcp.png', full_page=True)
        fail_tools[0] = True
        page.get_by_role('button', name='能力').click()
        page.reload(wait_until='networkidle')
        page.get_by_role('tab', name='工具', exact=True).click()
        expect(page.get_by_text('工具目录加载失败')).to_be_visible()
        expect(page.get_by_text('暂无内置工具')).to_have_count(0)
        expect(page.get_by_role('button', name='重试')).to_be_visible()
        page.goto(test_url + '/#/plugins', wait_until='networkidle')
        expect(page).to_have_url(test_url + '/#/skills#plugins')
        page.goto(test_url + '/#/settings?tab=briefing', wait_until='networkidle')
        settings_nav = page.get_by_role('navigation', name='设置分类')
        expect(settings_nav.get_by_role('button', name='简报', exact=True)).to_have_count(0)
        expect(settings_nav.get_by_role('button', name='插件', exact=True)).to_have_attribute('aria-current', 'page')
        expect(page.get_by_role('radio', name='功能', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='规则文稿', exact=True)).to_be_visible()
        page.screenshot(path='/tmp/stella-plugin-settings.png', full_page=True)
        page.goto(test_url + '/#/skills', wait_until='networkidle')
        fail_tools[0] = False
        page.reload(wait_until='networkidle')
        page.set_viewport_size({'width': 620, 'height': 900})
        expect(page.get_by_role('tab', name='插件', exact=True)).to_have_attribute('aria-selected', 'true')
        panel = page.get_by_role('tabpanel')
        heading_box = panel.get_by_role('heading', name='插件', exact=True).bounding_box()
        refresh_box = panel.get_by_role('button', name='刷新', exact=True).bounding_box()
        assert abs(heading_box['y'] + heading_box['height'] / 2 - refresh_box['y'] - refresh_box['height'] / 2) < 2, (heading_box, refresh_box)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/stella-plugins-compact-narrow.png', full_page=True)
        page.get_by_role('tab', name='插件', exact=True).focus()
        page.keyboard.press('ArrowRight')
        expect(page.get_by_role('tab', name='工具', exact=True)).to_be_focused()
        page.keyboard.press('End')
        expect(page.get_by_role('heading', name='MCP', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/stella-capabilities-narrow.png', full_page=True)
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.get_by_role('tab', name='插件', exact=True).click()
        page.screenshot(path='/tmp/stella-capabilities-desktop.png', full_page=True)
        assert plan_requests == [], 'Capabilities must not check for updates'
        page.goto(test_url + '/#/settings?tab=about', wait_until='networkidle')
        expect(page.get_by_role('heading', name='Core', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='Plugins', exact=True)).to_be_visible()
        expect(page.get_by_text('1.0.0 → 1.1.0', exact=True)).to_be_visible()
        expect(page.get_by_text('需要更新 Core', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='更新 stella.blocked')).to_be_disabled()
        fail_update[0] = True
        page.get_by_role('button', name='更新 stella.briefing').click()
        expect(page.get_by_role('alert')).to_contain_text('更新失败，请重试')
        fail_update[0] = False
        page.get_by_role('button', name='更新 stella.briefing').click()
        expect(page.get_by_role('button', name='更新 stella.briefing')).to_have_count(0)
        expect(page.get_by_role('status').filter(has_text='更新完成')).to_be_visible()
        fail_plan[0] = True
        page.get_by_role('button', name='检查插件更新', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('更新目录加载失败')
        expect(page.get_by_text('插件已是最新版本')).to_have_count(0)
        fail_plan[0] = False
        page.get_by_role('button', name='检查插件更新', exact=True).click()
        expect(page.get_by_text('需要更新 Core', exact=True)).to_be_visible()
        page.screenshot(path='/tmp/stella-about-updates.png', full_page=True)
        assert errors == [], errors
        print('PASS: horizontal capability tabs, plugin actions, MCP tools/error/retry/empty, legacy routes, nested briefing settings, desktop/narrow layouts')
    finally:
        browser.close()
