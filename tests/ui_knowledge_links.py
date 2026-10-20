"""Knowledge index links open the named document."""

import json
import os
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
plugin_enabled = [True]
DOCS = {
    'index.md': '# 索引\n\n[软件设计](assessment/software-design.md)\n',
    'assessment/software-design.md': '# 软件设计\n\n这是软件设计正文。\n',
}
LIST = {
    'status': 'success',
    'root_files': [{'name': 'index.md', 'title': '索引', 'size': 20}],
    'tree': [{'dir': 'assessment', 'files': [{'name': 'software-design.md', 'title': '软件设计', 'size': 20}], 'children': []}],
    'stats': {'pages': 2, 'size': 40},
    'enabled': True,
}


def backend(route):
    parsed = urlparse(route.request.url)
    path = parsed.path
    data = {'status': 'success'}
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
    elif path == '/api/plugins/runtime':
        data['plugins'] = [{'pluginId': 'stella.knowledge', 'intent': 'enabled' if plugin_enabled[0] else 'disabled',
                            'state': 'stopped', 'contributes': {'pages': ['knowledge.main']}},
            {'pluginId': 'stella.memory', 'intent': 'enabled' if plugin_enabled[0] else 'disabled',
             'state': 'stopped', 'contributes': {'pages': ['memory.main']}}]
    elif path == '/api/memory':
        data.update(list=[{'filename':'MEMORY.md','type':'global','size':42,'updated_at':'2026-10-20'}],total=1,page=1)
    elif path == '/api/memory/content':
        data.update(content='# 记忆正文\n\n独立记忆内容')
    elif path == '/api/knowledge/list':
        data.update(LIST)
    elif path == '/api/knowledge/read':
        target = parse_qs(parsed.query).get('path', [''])[0]
        data.update(content=DOCS.get(target, ''), path=target, dir='')
    elif path == '/api/knowledge/graph':
        data.update(nodes=[], edges=[])
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh');
          window.electronAPI = {platform: 'darwin',
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/knowledge', wait_until='networkidle')
        page.get_by_role('link', name='软件设计').click()
        expect(page.get_by_text('这是软件设计正文。')).to_be_visible()
        plugin_enabled[0] = False
        page.reload(wait_until='networkidle')
        expect(page.get_by_text('知识插件当前不可用', exact=True)).to_be_visible()
        expect(page.get_by_text('这是软件设计正文。')).to_have_count(0)
        plugin_enabled[0] = True
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(page.get_by_role('link', name='软件设计')).to_be_visible()
        page.set_viewport_size({'width': 620, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/stella-knowledge-plugin-narrow.png', full_page=True)
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.screenshot(path='/tmp/stella-knowledge-plugin-desktop.png', full_page=True)
        page.goto(url + '/#/memory', wait_until='networkidle')
        page.get_by_text('MEMORY.md', exact=True).click()
        expect(page.get_by_text('独立记忆内容', exact=True)).to_be_visible()
        plugin_enabled[0] = False
        page.reload(wait_until='networkidle')
        expect(page.get_by_text('记忆插件当前不可用', exact=True)).to_be_visible()
        expect(page.get_by_text('独立记忆内容', exact=True)).to_have_count(0)
        assert errors == [], errors
        print('PASS: knowledge links, independent plugin pages, disable and enable refresh, desktop/narrow layouts')
    finally:
        browser.close()
