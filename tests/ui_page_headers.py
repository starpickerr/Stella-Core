"""Page headers span the main pane; content width and chat stay unchanged."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
PAGES = [
    ('/#/tasks', '定时任务', True),
    ('/#/todos', '事务', False),
    ('/#/security', '安全中心', False),
    ('/#/settings', '设置', False),
    ('/#/models', '设置', False),
    ('/#/logs', '日志', False),
    ('/#/briefing', '简报', False),
    ('/#/calendar', '日程', False),
    ('/#/bills', '账单', False),
    ('/#/memory', '记忆管理', False),
    ('/#/knowledge', '知识库', False),
    ('/#/channels', '通道管理', False),
    ('/#/skills', '能力', False),
]


def backend(route):
    path = urlparse(route.request.url).path
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True, 'label': 'Test'}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path.startswith('/api/sessions'):
        data.update(sessions=[], total=0)
    elif path.startswith('/api/calendar'):
        data.update(events=[], categories=[])
    elif path == '/api/scheduler/destinations':
        data.update(destinations=[])
    elif path.startswith('/api/todos'):
        data.update(todos=[], reminders=[])
    elif path.startswith('/api/briefings'):
        data.update(briefings=[], sources=[], items=[], actions=[])
    elif path == '/api/scheduler':
        data.update(tasks=[])
    elif path.startswith('/api/security/activity'):
        data.update(records=[])
    elif path.startswith('/api/security/confirmations'):
        data.update(pending=[])
    elif path.startswith('/api/security'):
        data = {'status': 'error', 'message': 'fixture'}
    elif path.startswith('/api/channels'):
        data.update(channels=[])
    elif path == '/api/mcp':
        data['servers'] = []
    elif path == '/api/plugins/runtime':
        data['plugins'] = []
    elif path == '/api/plugins/dual-update-plan':
        data.update(updates=[], blocked=[])
    elif path.startswith('/api/tools'):
        data.update(tools=[])
    elif path.startswith('/api/skills'):
        data.update(skills=[])
    elif path.startswith('/api/knowledge'):
        data.update(stats={'pages': 0, 'size': 0}, categories=[], tree=[])
    elif path.startswith('/api/memory'):
        data.update(list=[], total=0, page=1)
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': test_url, 'Access-Control-Allow-Credentials': 'true'})


def measure(page):
    return page.evaluate("""() => {
      const pane = document.querySelector('[data-main-pane]').getBoundingClientRect()
      const header = document.querySelector('[data-page-header]').getBoundingClientRect()
      const root = document.documentElement
      return {
        left: Math.abs(header.left - pane.left),
        right: Math.abs(header.right - pane.right),
        scroll: root.scrollWidth - root.clientWidth,
        paneScroll: document.querySelector('[data-main-pane]').scrollWidth - document.querySelector('[data-main-pane]').clientWidth,
        tasksColumn: Boolean(document.querySelector('[data-main-pane] .max-w-3xl')),
      }
    }""")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
            getBackendPort: async () => 9876, getAppVersion: async () => '9.9.9',
            onBackendStatus: () => () => {}, getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        for route, title, tasks in PAGES:
            page.goto(test_url + route, wait_until='networkidle')
            header = page.locator('[data-page-header]')
            expect(header).to_be_visible()
            if page.get_by_role('heading', name=title).count() == 0:
                snap = page.evaluate("""() => ({
                  headers: [...document.querySelectorAll('[data-page-header]')].map((el) => el.innerText),
                  headings: [...document.querySelectorAll('h1,h2')].map((el) => el.innerText),
                })""")
                raise AssertionError((route, snap, page.url(), errors))
            box = measure(page)
            assert box['left'] <= 2 and box['right'] <= 2, (route, box)
            assert box['scroll'] <= 1 and box['paneScroll'] <= 1, (route, box)
            if tasks:
                assert box['tasksColumn'], route
        page.goto(test_url + '/#/', wait_until='networkidle')
        expect(page.locator('[data-page-header]')).to_have_count(0)
        page.set_viewport_size({'width': 390, 'height': 800})
        page.goto(test_url + '/#/tasks', wait_until='networkidle')
        collapse = page.get_by_title('收起侧栏')
        if collapse.count():
            collapse.click()
        box = measure(page)
        assert box['left'] <= 2 and box['right'] <= 2 and box['scroll'] <= 1 and box['paneScroll'] <= 1, box
        assert errors == [], errors
        print('Page headers: full-width titles, content width, and narrow layout passed')
    finally:
        browser.close()
