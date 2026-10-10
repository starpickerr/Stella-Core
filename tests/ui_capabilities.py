"""Capabilities page: tool grid with agent names, inline boundaries, skill toggle, and load errors."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
fail_tools = [False]
skill_posts = []
INTRO = '检索 Agent 的长期记忆；启用知识库时也可检索知识内容。这份介绍需要完整显示，不能被两行省略号截断。'
DETAIL = '只在带有记忆能力的对话中可用。它可以查找记忆和已启用的知识内容。'


def backend(route):
    path = urlparse(route.request.url).path
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
    elif path == '/api/skills' and method == 'POST':
        skill_posts.append(body)
    elif path == '/api/skills':
        data['skills'] = [{
            'name': 'demo-skill', 'display_name': '演示技能', 'enabled': True, 'source': 'custom',
            'description': '技能介绍需要完整显示。' * 8,
        }]
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/skills', wait_until='networkidle')
        nav = page.get_by_role('navigation')
        expect(nav.get_by_role('button', name='能力')).to_be_visible()
        expect(page.get_by_role('heading', name='能力')).to_be_visible()
        memory = page.get_by_role('article', name='memory_search')
        expect(memory.get_by_role('heading', name='memory_search', exact=True)).to_be_visible()
        expect(memory.get_by_text(INTRO)).to_be_visible()
        expect(memory.get_by_text('当前不可用')).to_be_visible()
        expect(page.get_by_text('搜索记忆', exact=True)).to_have_count(0)
        expect(page.get_by_text('读取文件', exact=True)).to_have_count(0)
        expect(page.get_by_text('查看详情')).to_have_count(0)
        expect(page.locator('.line-clamp-2')).to_have_count(0)
        read_box = page.get_by_role('article', name='read').bounding_box()
        memory_box = memory.bounding_box()
        assert abs(read_box['y'] - memory_box['y']) < 2 and memory_box['x'] > read_box['x'] + read_box['width'], (read_box, memory_box)

        expect(memory.get_by_text(DETAIL)).to_have_count(0)
        boundary = memory.get_by_role('button', name='适用说明')
        expect(boundary).to_have_attribute('aria-expanded', 'false')
        boundary.click()
        expect(boundary).to_have_attribute('aria-expanded', 'true')
        expect(memory.get_by_text(DETAIL)).to_be_visible()
        expect(memory.get_by_text('仅在启用记忆的对话中可用。')).to_be_visible()
        assert skill_posts == []

        page.goto(test_url + '/#/skills/tools/memory_search', wait_until='networkidle')
        expect(page).to_have_url(test_url + '/#/skills')

        demo = page.get_by_role('article', name='演示技能')
        expect(demo.get_by_text('技能介绍需要完整显示。', exact=False)).to_be_visible()
        assert skill_posts == []
        page.get_by_role('switch').click()
        page.wait_for_timeout(200)
        assert skill_posts and skill_posts[-1]['action'] == 'close'
        assert skill_posts[-1]['name'] == 'demo-skill'

        fail_tools[0] = True
        page.get_by_role('button', name='能力').click()
        page.reload(wait_until='networkidle')
        expect(page.get_by_text('工具目录加载失败')).to_be_visible()
        expect(page.get_by_text('暂无内置工具')).to_have_count(0)
        expect(page.get_by_role('button', name='重试')).to_be_visible()
        assert errors == [], errors
        print('Capabilities page: tool grid, raw names, inline boundaries, skill toggle, and error passed')
    finally:
        browser.close()
