"""Exercise the briefing report, detail view and explicit batch task creation."""
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
briefing = dict(id='brf-2026-10-08-morning', title='今日简报', status='completed', kind='morning',
                generated_at='2026-10-08T08:00:00Z', updated_at='2026-10-08T08:00:00Z',
                body='旧版纯文本报告', fetched_count=1, kept_count=1, filtered_count=0,
                source_windows={'elearning:campus': {'source':'elearning','account_id':'campus','name':'课程账号',
                    'start':'2026-10-07T08:00:00Z','end':'2026-10-08T08:00:00Z'}},
                mail_snapshot_available=True, error_message='')
item = dict(id='item-1', briefing_id=briefing['id'], source_item_id='source-1', title='算法设计大作业4',
            section='action', status='undo', source='elearning', account_id='campus', source_id='12:assignment:4',
            occurred_at='2026-10-08T08:00:00Z', score=80, sender='课程', snippet='10月29日截止',
            payload={'_briefing_reason':'课程作业有截止时间，需要处理', 'body':'完整作业要求与提交方式',
                     '_briefing_report':'完整 AI 分析：提交作业并核对截止时间'},
            url='https://example.test/assignment')


def pending_receipt():
    return dict(kind='todo', state='pending', target_id=None, business=None, error='', result={})


def action_view(category='needs_action', todo=None):
    return dict(category=category, change_type='new', information_type='assignment',
                facts={'course_id':'12', 'due_at':'2026-10-29T15:59:00Z', 'time_origin':'source'},
                todo=todo, calendar=None, reminder=None)


items = [item]
actions = {item['id']:action_view(todo=pending_receipt())}
mail = []
preferences = dict(show_low_priority=True, show_ongoing=True, important_types=[],
                   reminder_frequency='daily', summary_detail='brief')
decisions = []
sent_messages = []
created_todos = []
fail_next_message = [False]
fail_next_detail = [False]
today = date.today()
todo_rows = [
    dict(id='late', title='逾期作业', status='todo', due_on=(today - timedelta(days=2)).isoformat()),
    dict(id='open', title='明天的任务', status='todo', due_on=(today + timedelta(days=1)).isoformat()),
    dict(id='done', title='已完成旧任务', status='completed', due_on=(today - timedelta(days=3)).isoformat()),
    dict(id='project', title='项目任务', status='todo', due_on=(today + timedelta(days=1)).isoformat()),
    dict(id='middle', title='项目子任务', status='todo', due_on=(today + timedelta(days=1)).isoformat(), parent_id='project'),
    dict(id='deep', title='深层逾期任务', status='todo', due_on=(today - timedelta(days=1)).isoformat(), parent_id='middle'),
    dict(id='done-parent', title='已完成父事务', status='completed', due_on=(today - timedelta(days=3)).isoformat()),
    dict(id='late-under-done', title='父事务下的逾期事项', status='todo', due_on=(today - timedelta(days=1)).isoformat(), parent_id='done-parent'),
    dict(id='cancelled', title='已取消的事项', status='cancelled', due_on=(today - timedelta(days=4)).isoformat()),
]
todo_rows = [dict(dict(parent_id=None), **row, series_id=None, sort_order=index, planned_on=None, due_time=None,
                  timezone='Asia/Shanghai', priority=0, created_at='2026-10-01T00:00:00Z', notes='', list_name='', tags='[]',
                  flagged=0, blocked_by=[], subtask_count=0, progress_completed=0,
                  progress_total=0, progress_percent=0, repeat_frequency='none', remind_at=None)
             for index, row in enumerate(todo_rows)]


def backend(route):
    path = urlparse(route.request.url).path
    if path == '/api/briefings/' + briefing['id'] and fail_next_detail[0]:
        fail_next_detail[0] = False
        route.fulfill(status=503, content_type='application/json', body='{}',
                      headers={'Access-Control-Allow-Origin':test_url,'Access-Control-Allow-Credentials':'true'})
        return
    body = route.request.post_data_json if route.request.method == 'POST' else None
    data = {'status':'success'}
    if path == '/api/health':
        data = {'status':'ok'}
    elif path == '/auth/check':
        data.update(auth_required=False, authenticated=True)
    elif path == '/api/models':
        data.update(providers=[{'id':'test','configured':True}], capabilities={'chat':{'current_provider':'test','current_model':'test'}})
    elif path == '/api/briefings':
        data['briefings'] = [briefing]
    elif path == '/api/briefings/' + briefing['id']:
        data.update(briefing=briefing, items=items, mail=mail, revisions=[], actions=actions, preferences=preferences)
    elif path == '/api/briefings/overview':
        data.update(items=items, actions=actions, preferences=preferences)
    elif path == '/api/briefings/actions':
        decision = body['decision']
        decisions.append({'id':body['id'], **decision})
        receipt = actions[body['id']]['todo'] or pending_receipt()
        actions[body['id']]['todo'] = receipt
        if decision['operation'] == 'link':
            receipt.update(state='succeeded', target_id=decision['target_id'], error='',
                           business={'id':decision['target_id'],'title':'已有事务','status':'todo'},
                           result={'operation':'linked'})
        elif body['id'] == 'item-4':
            receipt.update(state='pending', result={'operation':'matching_required'})
        elif len(decisions) == 1:
            receipt.update(state='failed', error='临时写入失败', result={'operation':'failed'})
        else:
            receipt.update(state='succeeded', target_id=body['id'], error='',
                           business={'id':body['id'],'title':decision.get('title'),'status':'todo'},
                           result={'operation':'created'})
        if body['id'] == 'item-5':
            fail_next_detail[0] = True
        data['receipt'] = receipt
    elif path == '/api/briefings/actions/targets':
        data['targets'] = [{'id':'existing-task','title':'已有事务','status':'todo'}]
    elif path == '/api/briefings/sources':
        data['sources'] = [{'id':'elearning:campus','source':'elearning','account_id':'campus','name':'课程账号'}]
    elif path == '/api/briefings/rules':
        data.update(rules=[], default_text='保留重要课程通知')
    elif path == '/api/briefings/mailboxes':
        data['mailboxes'] = []
    elif path == '/api/briefings/elearning':
        data['settings'] = {'enabled':False,'courses':[]}
    elif path == '/api/briefings/authorizations':
        data['rules'] = []
    elif path == '/api/briefings/preferences':
        if body:
            preferences.update(body)
        data['preferences'] = preferences
    elif path == '/api/todos':
        if route.request.method == 'POST':
            created_todos.append(body)
        data['todos'] = todo_rows
    elif path == '/message':
        sent_messages.append(body)
        if fail_next_message[0]:
            fail_next_message[0] = False
            route.fulfill(status=503, content_type='application/json', body='{}',
                          headers={'Access-Control-Allow-Origin':test_url,'Access-Control-Allow-Credentials':'true'})
            return
        data.update(request_id='', stream=False, inline_reply='已接收事务要求')
    elif path == '/api/todos/reminders/uncertain':
        data['reminders'] = []
    else:
        data.update(sessions=[], projects=[], messages=[], skills=[], tasks=[], agents=[], admissions=[])
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin':test_url,'Access-Control-Allow-Credentials':'true'})


def add_item(number, title, *, category='needs_action', todo=True, reason=None, body=None):
    row = {**item, 'id':f'item-{number}', 'source_item_id':f'source-{number}',
           'title':title, 'source_id':f'12:assignment:{number}',
           'payload':({'_briefing_reason':reason} if reason else {}) | ({'body':body} if body else {})}
    items.append(row)
    actions[row['id']] = action_view(category=category, todo=pending_receipt() if todo else None)
    return row


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width':1440,'height':900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang', 'zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {},
            getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/briefing', wait_until='networkidle')
        page.get_by_text('今日简报', exact=True).first.click()

        report = page.get_by_role('region', name='AI 报告')
        create = report.get_by_role('button', name='建立事务', exact=False)
        checkbox = report.get_by_role('checkbox', name='选择 算法设计大作业4')
        expect(create).to_be_visible()
        expect(create).to_be_disabled()
        expect(checkbox).to_be_enabled()
        desktop_screenshot = Path(os.environ.get('STELLA_SCREENSHOT_DIR', os.environ.get('TMPDIR', '/tmp'))) / 'stella-briefing-report-desktop.png'
        page.screenshot(path=str(desktop_screenshot), full_page=True)
        title_box = report.get_by_role('heading', name='AI 报告').bounding_box()
        create_box = create.bounding_box()
        assert title_box and create_box and create_box['x'] > title_box['x'] + title_box['width']
        expect(report.get_by_text('查看报告全文', exact=True)).to_have_count(0)
        expect(page.get_by_text('旧版纯文本报告', exact=True)).to_have_count(0)
        for removed in ('关联已有', '仅保留简报', '暂不处理', '忽略建议', '创建日程', '更多'):
            expect(report.get_by_role('button', name=removed, exact=True)).to_have_count(0)
        report.get_by_role('button', name='查看 算法设计大作业4').click()
        expect(report.get_by_role('heading', name='算法设计大作业4')).to_be_focused()
        expect(report.get_by_text('具体内容', exact=True)).to_be_visible()
        expect(report.get_by_text('完整 AI 分析：提交作业并核对截止时间', exact=True)).to_be_visible()
        expect(report.get_by_text('完整作业要求与提交方式', exact=True)).to_be_visible()
        expect(report.get_by_text('AI 判断依据', exact=True)).to_be_visible()
        expect(report.get_by_text('课程作业有截止时间，需要处理', exact=True)).to_be_visible()
        expect(report.get_by_role('link', name='打开来源', exact=True)).to_be_visible()
        report.get_by_role('button', name='返回报告').click()
        expect(report.get_by_role('button', name='查看 算法设计大作业4')).to_be_focused()

        checkbox.check()
        expect(create).to_be_enabled()
        assert decisions == []
        create.click()
        expect(report.get_by_text('临时写入失败', exact=False)).to_be_visible()
        expect(checkbox).to_be_checked()
        create.click()
        expect(report.get_by_role('button', name='查看 算法设计大作业4')).to_contain_text('已关联事务')
        checkbox.check()
        expect(checkbox).to_be_checked()
        expect(create).to_be_disabled()
        checkbox.uncheck()

        informational = add_item('info', '课程资料通知', category='attention', todo=False)
        informational['section'] = 'fyi'
        informational['snippet'] = '教材资料已更新'
        mail.append(dict(id='source-info', source='elearning', account_id='campus', source_id=informational['source_id'],
                         thread_id='', sender='课程', sender_email='', title=informational['title'],
                         snippet=informational['snippet'], occurred_at=informational['occurred_at'],
                         url=informational['url'], body='教材第 4 章已更新', body_available=True,
                         category='selected', filter_reason='资料更新值得关注，无需立即处理'))
        page.get_by_role('button', name='刷新', exact=True).click()
        info_checkbox = report.get_by_role('checkbox', name='选择 课程资料通知')
        expect(info_checkbox).to_be_enabled()
        report.get_by_role('button', name='查看 课程资料通知').click()
        expect(report.get_by_text('教材第 4 章已更新', exact=True)).to_be_visible()
        expect(report.get_by_text('资料更新值得关注，无需立即处理', exact=True)).to_be_visible()
        report.get_by_role('button', name='返回报告').click()
        info_checkbox.check()
        expect(create).to_be_enabled()
        create.click()
        expect(report.get_by_text('已关联事务', exact=False)).to_have_count(2)

        add_item(2, '待生成事务2')
        add_item(3, '待生成事务3')
        page.get_by_role('button', name='刷新', exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        screenshot = Path(os.environ.get('STELLA_SCREENSHOT_DIR', os.environ.get('TMPDIR', '/tmp'))) / 'stella-briefing-report-mobile.png'
        page.screenshot(path=str(screenshot), full_page=True)
        before = len(decisions)
        report.get_by_role('checkbox', name='全选', exact=True).check()
        expect(report.get_by_role('checkbox', name='选择 待生成事务3')).to_be_checked()
        expect(create).to_contain_text('(2)')
        create.click()
        expect(report.get_by_role('button', name='查看 待生成事务2')).to_contain_text('已关联事务')
        expect(report.get_by_role('button', name='查看 待生成事务3')).to_contain_text('已关联事务')
        assert len(decisions) == before + 2
        page.set_viewport_size({'width':1440,'height':900})

        add_item(4, '需匹配已有事务')
        page.get_by_role('button', name='刷新', exact=True).click()
        report.get_by_role('checkbox', name='选择 需匹配已有事务').check()
        create.click()
        expect(report.get_by_role('checkbox', name='选择 需匹配已有事务')).to_be_checked()
        expect(report.get_by_text('1 项事务未建立', exact=False)).to_be_visible()
        expect(create).to_be_enabled()
        create.click()
        dialog = page.get_by_role('dialog', name='关联已有')
        expect(dialog).to_be_visible()
        dialog.get_by_role('button', name='已有事务').click()
        expect(dialog).to_have_count(0)
        expect(report.get_by_role('checkbox', name='选择 需匹配已有事务')).not_to_be_checked()

        add_item(5, '刷新失败后仍已创建')
        page.get_by_role('button', name='刷新', exact=True).click()
        report.get_by_role('checkbox', name='选择 刷新失败后仍已创建').check()
        before = len(decisions)
        create.click()
        expect(page.get_by_text('HTTP 503', exact=False)).to_be_visible()
        expect(create).to_be_disabled()
        assert len(decisions) == before + 1
        thread = add_item(6, '课程修订通知', reason='需核对新要求', body='旧版要求')
        thread['payload'].update(_briefing_report='完整 AI 分析：核对两封通知的差异',
                                 _briefing_members=[
                                     {'title':'原通知','body':'旧版要求','reason':'原通知需要关注','url':'https://example.test/old'},
                                     {'title':'修订通知','body':'新版要求','reason':'新要求需要处理','url':'https://example.test/new'}])
        page.get_by_role('button', name='刷新', exact=True).click()
        report.get_by_role('button', name='查看 课程修订通知').click()
        expect(report.get_by_text('旧版要求', exact=True)).to_be_visible()
        expect(report.get_by_text('新版要求', exact=True)).to_be_visible()
        expect(report.get_by_text('原通知需要关注', exact=True)).to_be_visible()
        expect(report.get_by_text('新要求需要处理', exact=True)).to_be_visible()
        expect(report.get_by_role('link', name='打开来源', exact=True)).to_have_count(2)
        preferences['show_low_priority'] = False
        for row in items:
            actions[row['id']]['category'] = 'other'
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(report.get_by_text('旧版纯文本报告', exact=True)).to_have_count(0)
        preferences['show_low_priority'] = True
        items.clear()
        page.get_by_role('button', name='刷新', exact=True).click()
        expect(report.get_by_text('旧版纯文本报告', exact=True)).to_be_visible()
        expect(report.get_by_text('查看报告全文', exact=True)).to_have_count(0)

        page.goto(test_url + '/#/todos', wait_until='networkidle')
        tabs = page.get_by_role('navigation', name='事务')
        expect(tabs.get_by_role('button', name='逾期 3')).to_be_visible()
        assert page.get_by_role('heading', name='逾期 3').bounding_box()['y'] < page.get_by_role('heading', name='已取消 1').bounding_box()['y'] < page.get_by_role('heading', name='已完成 1').bounding_box()['y']
        expect(page.get_by_role('heading', name='逾期 3').locator('..').get_by_text('项目任务', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='逾期 3').locator('..').get_by_text('已完成父事务', exact=True)).to_be_visible()
        tabs.get_by_role('button', name='逾期 3').click()
        expect(page.get_by_text('逾期作业', exact=True)).to_be_visible()
        expect(page.get_by_text('深层逾期任务', exact=True)).to_be_visible()
        expect(page.get_by_role('heading', name='逾期 3').locator('..').get_by_text('已完成父事务', exact=True)).to_be_visible()
        expect(page.get_by_text('父事务下的逾期事项', exact=True)).to_be_visible()
        expect(page.get_by_text('明天的任务', exact=True)).to_have_count(0)
        tabs.get_by_role('button', name='未完成 2').click()
        expect(page.get_by_text('明天的任务', exact=True)).to_be_visible()
        expect(page.get_by_text('逾期作业', exact=True)).to_have_count(0)
        expect(page.get_by_text('深层逾期任务', exact=True)).to_have_count(0)
        tabs.get_by_role('button', name='全部事务 6').click()
        task_screenshot = Path(os.environ.get('STELLA_SCREENSHOT_DIR', os.environ.get('TMPDIR', '/tmp'))) / 'stella-tasks-overdue-desktop.png'
        page.screenshot(path=str(task_screenshot), full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        task_mobile_screenshot = task_screenshot.with_name('stella-tasks-overdue-mobile.png')
        page.screenshot(path=str(task_mobile_screenshot), full_page=True)
        quick = page.locator('form').filter(has=page.locator('#todo-quick-title'))
        add_box = quick.get_by_role('button', name='Agent 管理').bounding_box()
        form_box = quick.bounding_box()
        assert add_box and form_box and add_box['x'] + add_box['width'] <= form_box['x'] + form_box['width']
        expect(quick.locator('svg.lucide-circle')).to_have_count(0)
        expect(quick.get_by_role('button', name='直接添加')).to_be_visible()
        expect(quick.get_by_role('button', name='交给 Agent', exact=True)).to_have_count(0)
        agent = quick.get_by_role('button', name='Agent 管理')
        expect(agent).to_be_disabled()
        quick.get_by_role('textbox', name='需要完成什么？').fill('整理课程资料')
        expect(agent).to_be_enabled()
        quick.get_by_role('button', name='更多选项').click()
        quick.get_by_label('截止日期').fill((today + timedelta(days=2)).isoformat())
        agent.click()
        expect(page.get_by_text('已接收事务要求', exact=True).last).to_be_visible()
        assert len(sent_messages) == 1
        assert sent_messages[0]['session_id']
        assert '使用 todos 事务工具建立' in sent_messages[0]['message']
        assert '整理课程资料' in sent_messages[0]['message']
        assert (today + timedelta(days=2)).isoformat() in sent_messages[0]['message']
        assert created_todos == []

        page.goto(test_url + '/#/todos', wait_until='networkidle')
        fail_next_message[0] = True
        page.get_by_role('textbox', name='需要完成什么？').fill('失败后重试的事务')
        page.get_by_role('button', name='Agent 管理').click()
        expect(page.get_by_text('HTTP 503', exact=False)).to_be_visible()
        page.goto(test_url + '/#/todos', wait_until='networkidle')
        page.get_by_role('textbox', name='需要完成什么？').fill('失败后重试的事务')
        page.get_by_role('button', name='Agent 管理').click()
        expect(page.get_by_text('已接收事务要求', exact=True).last).to_be_visible()
        assert len(sent_messages) == 3
        assert created_todos == []

        quick.get_by_role('textbox', name='需要完成什么？').fill('直接添加事务')
        quick.get_by_role('button', name='直接添加').click()
        expect(quick.get_by_role('textbox', name='需要完成什么？')).to_have_value('')
        assert created_todos[-1]['title'] == '直接添加事务'

        todo_rows.append({**todo_rows[0], 'id':'timed', 'title':'到点转逾期',
                          'due_on':today.isoformat(), 'due_time':'12:01'})
        clock_page = browser.new_page()
        clock_page.add_init_script("""localStorage.setItem('stella_lang', 'zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {},
            getBackendError: async () => null
        };""")
        clock_page.route('http://127.0.0.1:9876/**', backend)
        clock_page.clock.install(time=datetime.combine(today, time(12, 0, 30), ZoneInfo('Asia/Shanghai')))
        clock_page.goto(test_url + '/#/todos', wait_until='networkidle')
        clock_tabs = clock_page.get_by_role('navigation', name='事务')
        expect(clock_tabs.get_by_role('button', name='逾期 3')).to_be_visible()
        clock_page.clock.run_for(46_000)
        expect(clock_tabs.get_by_role('button', name='逾期 4')).to_be_visible()
        clock_page.close()
        assert errors == [], errors
        print('UI briefing and tasks: report, overdue views, ordering, Agent creation dispatch/retry PASS')
    finally:
        browser.close()
