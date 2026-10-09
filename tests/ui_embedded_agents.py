"""Mount the shared embedded chat in the renderer with an isolated backend."""

import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
sent = []
created = []
event_reads = []
todo_reads = []
pending = [None]
approvals = []


def backend(route):
    path = urlparse(route.request.url).path
    body = route.request.post_data_json if route.request.method == 'POST' else {}
    data = {'status': 'success'}
    if path == '/api/health':
        data = {'status': 'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id': 'test', 'configured': True}],
                    capabilities={'chat': {'current_provider': 'test', 'current_model': 'test'}})
    elif path == '/api/history':
        data.update(messages=[], total=0, page=1, page_size=20, has_more=False)
    elif path == '/message':
        sent.append(body)
        if body['message'] == '长任务':
            pending[0] = body['session_id']
            data.update(stream=True, request_id='long-request')
        else:
            data.update(stream=False, inline_reply='已处理：' + body['message'])
    elif path == '/api/security/confirmations':
        data['pending'] = [dict(id='approval-1', tool='AppleTool', session=pending[0],
                                summary='写入日程', resource='calendar', risk='write', reason='需要确认',
                                expanded_scope='', effect='添加条目')] if pending[0] else []
        if route.request.method == 'POST':
            approvals.append(body)
            pending[0] = None
    elif path == '/api/calendar/events':
        event_reads.append(path)
        data['events'] = []
    elif path == '/api/calendar/categories':
        data['categories'] = []
    elif path == '/api/todos':
        if route.request.method == 'POST':
            created.append(body)
            data['todo'] = {'id': 'direct-1', **body}
        else:
            todo_reads.append(path)
            data['todos'] = []
    elif path == '/api/todos/reminders/uncertain':
        data['reminders'] = []
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin': url, 'Access-Control-Allow-Credentials': 'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang','zh'); window.electronAPI = {
          getBackendPort: async () => 9876, onBackendStatus: () => () => {}, getBackendError: async () => null
        }; window.EventSource = class {
          constructor() {
            this.closed = false
            setTimeout(() => { if (!this.closed) this.onmessage?.({data: JSON.stringify({type:'tool_start',tool_call_id:'step-1',tool:'AppleTool',arguments:{action:'sync'}})}) }, 100)
            setTimeout(() => { if (!this.closed) this.onmessage?.({data: JSON.stringify({type:'done',content:'任务完成'})}) }, 2500)
          }
          close() { this.closed = true }
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(url + '/#/settings?tab=basic', wait_until='networkidle')
        page.evaluate("""async () => {
          await import('/src/__test__/EmbeddedAgentHarness.tsx')
          window.mountEmbedded('calendar', { id: 'preset-1', text: '请创建读书日程' })
        }""")
        embedded = page.locator('#embedded-test-root')
        expect(embedded.get_by_text('已处理：请创建读书日程')).to_be_visible()
        assert len(sent) == 1 and sent[0]['message'] == '请创建读书日程'
        calendar_session = sent[0]['session_id']
        page.evaluate("window.mountEmbedded('todos', null)")
        embedded.get_by_role('button', name='展开 Agent').click()
        todo_input = embedded.locator('textarea')
        todo_input.fill('提醒我买书')
        page.evaluate("window.mountEmbedded('calendar', { id: 'preset-1', text: '请创建读书日程' })")
        embedded.get_by_role('button', name='展开 Agent').click()
        expect(embedded.locator('textarea')).to_have_value('')
        embedded.locator('textarea').fill('calendar draft')
        page.evaluate("window.mountEmbedded('todos', null)")
        embedded.get_by_role('button', name='展开 Agent').click()
        expect(embedded.locator('textarea')).to_have_value('提醒我买书')
        embedded.locator('textarea').fill('')
        embedded.locator('textarea').fill('新增读书事务')
        embedded.locator('textarea').press('Enter')
        expect(embedded.get_by_text('已处理：新增读书事务')).to_be_visible()
        assert sent[-1]['session_id'] != calendar_session
        page.evaluate("window.mountEmbedded('calendar', { id: 'preset-1', text: '请创建读书日程' })")
        embedded.get_by_role('button', name='展开 Agent').click()
        expect(embedded.locator('textarea')).to_have_value('calendar draft')
        assert len(sent) == 2, sent
        embedded.locator('textarea').fill('长任务')
        embedded.locator('textarea').press('Enter')
        expect(page.get_by_role('dialog', name='审批操作')).to_be_visible()
        expect(embedded.get_by_text('AppleTool')).to_be_visible()
        page.get_by_role('dialog', name='审批操作').get_by_role('button', name='允许一次').click()
        assert approvals[0]['action'] == 'approve'
        embedded.get_by_role('button', name='收起 Agent').click()
        page.evaluate('window.detachEmbedded()')
        page.wait_for_timeout(2700)
        page.evaluate("window.mountEmbedded('calendar', null)")
        embedded.get_by_role('button', name='展开 Agent').click()
        expect(embedded.get_by_text('任务完成')).to_be_visible()
        assert sent[-1]['session_id'] == calendar_session
        page.evaluate("window.detachEmbedded(); document.getElementById('embedded-test-root').remove()")
        page.goto(url + '/#/calendar', wait_until='networkidle')
        prior_calendar_reads = len(event_reads)
        page.get_by_role('button', name='Apple 日历').click()
        page.get_by_role('menuitem', name='从 Apple 导入（Agent）').click()
        expect(page.get_by_role('region', name='日程 Agent')).to_be_visible()
        expect(page.get_by_text('已处理：请查看 Apple 日历权限', exact=False)).to_be_visible()
        expect(page).to_have_url(url + '/#/calendar')
        assert 'Apple 日历' in sent[-1]['message']
        assert len(event_reads) > prior_calendar_reads
        page.get_by_role('button', name='Apple 日历').click()
        page.get_by_role('menuitem', name='管理 Apple 日历').click()
        expect(page).to_have_url(url + '/#/settings?tab=integrations&section=apple-calendar')
        page.goto(url + '/#/todos', wait_until='networkidle')
        quick = page.locator('form').filter(has=page.locator('#todo-quick-title'))
        quick.get_by_role('textbox').fill('直接创建的事项')
        quick.get_by_role('button', name='直接添加').click()
        assert created[-1]['title'] == '直接创建的事项'
        quick.get_by_role('textbox').fill('用 Agent 整理项目')
        prior_todo_reads = len(todo_reads)
        quick.get_by_role('button', name='Agent 管理').click()
        expect(page).to_have_url(url + '/#/todos')
        expect(page.get_by_role('region', name='事务 Agent')).to_be_visible()
        expect(page.get_by_text('已处理：请使用 todos 事务工具', exact=False)).to_be_visible()
        assert '用 Agent 整理项目' in sent[-1]['message']
        assert len(todo_reads) > prior_todo_reads
        quick.get_by_role('button', name='Apple 提醒事项').click()
        quick.get_by_role('menuitem', name='从 Apple 导入（Agent）').click()
        assert 'Apple 提醒事项' in sent[-1]['message']
        quick.get_by_role('button', name='Apple 提醒事项').click()
        quick.get_by_role('menuitem', name='管理 Apple 提醒事项').click()
        expect(page).to_have_url(url + '/#/settings?tab=integrations&section=apple-reminders')
        assert errors == [], errors
        print('Embedded Agent UI: sessions, streams, approval and page actions passed')
    finally:
        browser.close()
