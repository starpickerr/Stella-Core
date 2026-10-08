"""Exercise briefing decisions and scoped preferences with a controlled backend."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


test_url = os.environ.get('STELLA_TEST_URL', 'http://127.0.0.1:5173')
briefing = dict(id='brf-2026-10-08-morning', title='今日简报', status='completed', kind='morning',
                generated_at='2026-10-08T08:00:00Z', updated_at='2026-10-08T08:00:00Z',
                body='AI 精简概览', fetched_count=1, kept_count=1, filtered_count=0,
                source_windows={'elearning:campus': {'source':'elearning','account_id':'campus','name':'课程账号','start':'2026-10-07T08:00:00Z','end':'2026-10-08T08:00:00Z'}}, mail_snapshot_available=True, error_message='')
item = dict(id='item-1', briefing_id=briefing['id'], title='算法设计大作业4', section='action',
            status='undo', source='elearning', account_id='campus', source_id='12:assignment:4',
            occurred_at='2026-10-08T08:00:00Z', score=80, sender='课程', snippet='10月29日截止',
            payload={}, url='https://example.test/assignment')
receipt = dict(state='pending', kind='todo', target_id=None, business=None, error='', result={})
action = dict(category='needs_action', change_type='new', information_type='assignment',
              facts={'course_id':'12', 'due_at':'2026-10-29T15:59:00Z', 'time_origin':'source'},
              todo=receipt, calendar=None, reminder=None)
items = [item]
actions = {item['id']: action}
preferences = dict(show_low_priority=True, show_ongoing=True, important_types=[],
                   reminder_frequency='daily', summary_detail='brief')
decisions = []
rules = []
fail_next_detail = [False]
calendar_event = dict(id='future-event',title='未来课程会议',start_at='2099-12-10T01:00:00+00:00',end_at='2099-12-10T02:00:00+00:00',
    description='已关联日程详情',all_day=False,category_id=None,repeat_frequency='none',repeat_days=[],location='',repeat_until=None)


def backend(route):
    path = urlparse(route.request.url).path
    if path == '/api/briefings/' + briefing['id'] and fail_next_detail[0]:
        fail_next_detail[0] = False
        route.fulfill(status=503, content_type='application/json', body=json.dumps({'status':'error','message':'刷新暂时失败'}),
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
        data.update(briefing=briefing, items=items, mail=[], revisions=[], actions=actions, preferences=preferences)
    elif path == '/api/briefings/overview':
        data.update(items=items,actions=actions,preferences=preferences)
    elif path == '/api/calendar/events':
        data['events'] = [calendar_event]
    elif path == '/api/calendar/categories':
        data['categories'] = []
    elif path == '/api/briefings/actions/targets':
        data['targets'] = [{'id':'existing','title':'已有学习事务','status':'todo'}]
    elif path == '/api/briefings/actions':
        decision = body['decision']
        target_receipt = actions[body['id']]['todo'] if decision.get('kind') == 'todo' else receipt
        decisions.append(decision)
        operation = decision['operation']
        if decision.get('kind') == 'reminder' and operation == 'retry':
            action['reminder'].update(state='succeeded',error='',result={'operation':'reminder_configured'})
            data['receipt'] = action['reminder']
        elif decision.get('kind') == 'calendar' and operation == 'confirm_update':
            action['calendar'].update(state='succeeded',error='',result={'operation':'synced'})
            data['receipt'] = action['calendar']
        elif operation in {'create','retry','link'}:
            awaiting_match = body['id'] == 'item-4'
            target_receipt.update(state='pending' if awaiting_match else 'failed' if len(decisions) == 1 else 'succeeded',
                           error='临时写入失败' if len(decisions) == 1 else '',
                           target_id=None if awaiting_match or len(decisions) == 1 else 'existing',
                           business=None if awaiting_match or len(decisions) == 1 else {'id':'existing','title':'已有学习事务','status':'todo'},
                           result={'operation':'created' if operation != 'link' else 'linked'})
            if body['id'] == 'item-5':
                fail_next_detail[0] = True
        elif operation == 'unlink':
            target_receipt.update(state='detached', target_id=None, business=None)
        data.setdefault('receipt', target_receipt)
    elif path == '/api/briefings/authorizations':
        if body:
            rules.append({**body,'id':'rule-1'})
            data['rule'] = rules[-1]
        data['rules'] = rules
    elif path == '/api/briefings/authorizations/delete':
        rules.clear()
    elif path == '/api/briefings/preferences':
        if body:
            preferences.update(body)
        data['preferences'] = preferences
    elif path == '/api/briefings/sources':
        data['sources'] = [{'id':'elearning:campus','source':'elearning','account_id':'campus','name':'课程账号'}]
    elif path == '/api/briefings/rules':
        data.update(rules=[], default_text='保留重要课程通知')
    elif path == '/api/briefings/mailboxes':
        data['mailboxes'] = []
    elif path == '/api/briefings/elearning':
        data['settings'] = {'enabled':False,'courses':[]}
    else:
        data.update(sessions=[], projects=[], messages=[], skills=[], tasks=[], agents=[], admissions=[])
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data),
                  headers={'Access-Control-Allow-Origin':test_url,'Access-Control-Allow-Credentials':'true'})


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""localStorage.setItem('stella_lang', 'zh'); window.electronAPI = {
            getBackendPort: async () => 9876, onBackendStatus: () => () => {},
            getBackendError: async () => null
        };""")
        page.route('http://127.0.0.1:9876/**', backend)
        page.goto(test_url + '/#/briefing', wait_until='networkidle')
        page.get_by_text('今日简报', exact=True).first.click()
        expect(page.get_by_text('AI 报告', exact=True)).to_be_visible()
        expect(page.get_by_text('事实、判断与执行结果', exact=True)).to_be_visible()
        expect(page.get_by_label(item['title'] + ': 信息阅读状态')).to_have_count(0)
        expect(page.get_by_role('button', name='创建事务', exact=True)).to_have_count(0)
        expect(page.get_by_text('来源与时间窗口', exact=True)).to_be_visible()
        page.get_by_text('来源与时间窗口', exact=True).click()
        expect(page.get_by_text('课程账号：', exact=False)).to_be_visible()
        expect(page.get_by_role('link', name='打开来源', exact=True)).to_be_visible()
        item_checkbox = page.get_by_role('checkbox', name='选择 算法设计大作业4')
        expect(item_checkbox).not_to_be_checked()
        assert decisions == []
        page.get_by_role('checkbox', name='全选可生成事务的信息').check()
        expect(item_checkbox).to_be_checked()
        page.get_by_role('button', name='生成事务', exact=False).click()
        expect(page.get_by_role('article').get_by_text('临时写入失败', exact=False)).to_be_visible()
        page.get_by_role('button', name='重试', exact=True).last.click()
        expect(page.get_by_role('link', name='查看事务', exact=True)).to_be_visible()
        assert decisions[-1]['operation'] == 'retry'
        page.get_by_text('更多', exact=True).click()
        page.get_by_role('button', name='解除关联', exact=True).click()
        page.get_by_role('button', name='关联已有', exact=True).click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_label('搜索事务').fill('学习')
        dialog.get_by_role('button', name='已有学习事务', exact=False).click()
        assert decisions[-1]['operation'] == 'link'
        action['reminder'] = dict(kind='reminder',state='failed',target_id='existing',business=receipt['business'],error='取消提醒失败',result={'operation':'failed'})
        page.get_by_role('button', name='刷新', exact=True).click()
        page.get_by_role('button', name='重试', exact=True).click()
        expect(page.get_by_text('取消提醒失败', exact=False)).to_have_count(0)
        assert decisions[-1] == {'operation':'retry','kind':'reminder'}
        action['calendar'] = dict(kind='calendar',state='conflict',target_id=calendar_event['id'],business=calendar_event,error='活动时间变更需确认',result={'operation':'confirmation_required'})
        page.get_by_role('button', name='刷新', exact=True).click()
        page.get_by_role('button', name='确认更新', exact=True).click()
        expect(page.get_by_text('活动时间变更需确认', exact=False)).to_have_count(0)
        assert decisions[-1] == {'operation':'confirm_update','kind':'calendar'}
        page.get_by_role('button', name='简报设置', exact=True).click()
        page.get_by_label('显示低优先级动态').uncheck()
        page.get_by_role('button', name='保存显示偏好', exact=True).click()
        expect(page.get_by_text('偏好已保存', exact=True)).to_be_visible()
        assert preferences['show_low_priority'] is False
        page.get_by_label('授权来源').select_option('elearning:campus')
        page.get_by_label('信息类型', exact=True).select_option('assignment')
        page.get_by_label('课程范围', exact=True).filter(visible=True).last.fill('12')
        page.get_by_role('button', name='保存授权规则', exact=True).click()
        expect(page.get_by_role('button', name='撤销', exact=True)).to_be_visible()
        assert rules[0]['account_id'] == 'campus' and rules[0]['course_id'] == '12'
        page.get_by_role('button', name='撤销', exact=True).click()
        expect(page.get_by_role('button', name='撤销', exact=True)).to_have_count(0)
        assert rules == []
        page.get_by_role('button', name='返回简报', exact=True).click()
        page.get_by_role('button', name='完整概览', exact=True).click()
        expect(page.get_by_role('link', name='查看事务', exact=True)).to_be_visible()
        page.set_viewport_size({'width':900,'height':900})
        expect(page.get_by_role('link', name='查看事务', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        narrow_screenshot = Path(os.environ.get('STELLA_SCREENSHOT_DIR', os.environ.get('TMPDIR', '/tmp'))) / 'stella-briefing-narrow-desktop.png'
        page.screenshot(path=str(narrow_screenshot), full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        expect(page.get_by_role('link', name='查看事务', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        screenshot = Path(os.environ.get('STELLA_SCREENSHOT_DIR', os.environ.get('TMPDIR', '/tmp'))) / 'stella-briefing-mobile.png'
        page.screenshot(path=str(screenshot), full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        action['calendar'] = dict(kind='calendar',state='succeeded',target_id=calendar_event['id'],business=calendar_event,error='',result={'operation':'linked'})
        page.get_by_role('button', name='刷新', exact=True).click()
        page.get_by_role('link', name='查看日程', exact=True).click()
        expect(page.locator('button[aria-expanded]').filter(has_text='未来课程会议')).to_have_attribute('aria-expanded','true')
        expect(page.get_by_text('已关联日程详情', exact=True)).to_be_visible()
        for number in (2, 3):
            extra = {**item, 'id':f'item-{number}', 'title':f'待生成事务{number}', 'source_id':f'12:assignment:{number}'}
            items.append(extra)
            actions[extra['id']] = {**action, 'todo':dict(kind='todo',state='pending',target_id=None,business=None,error='',result={}), 'calendar':None, 'reminder':None}
        informational = {**item, 'id':'item-info', 'title':'课程资料通知', 'section':'fyi', 'source_id':'12:material:1'}
        items.append(informational)
        actions[informational['id']] = {**action, 'category':'attention', 'information_type':'material', 'todo':None, 'calendar':None, 'reminder':None}
        page.goto(test_url + '/#/briefing', wait_until='networkidle')
        page.get_by_text('今日简报', exact=True).first.click()
        expect(page.get_by_role('checkbox', name='选择 待生成事务2')).to_be_visible()
        expect(page.get_by_role('checkbox', name='选择 课程资料通知')).to_be_disabled()
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        mobile_batch_screenshot = Path(os.environ.get('STELLA_SCREENSHOT_DIR', os.environ.get('TMPDIR', '/tmp'))) / 'stella-briefing-mobile-batch.png'
        page.screenshot(path=str(mobile_batch_screenshot), full_page=True)
        before = len(decisions)
        page.get_by_role('checkbox', name='全选可生成事务的信息').check()
        expect(page.get_by_role('checkbox', name='选择 待生成事务3')).to_be_checked()
        assert len(decisions) == before
        page.get_by_role('button', name='生成事务', exact=False).click()
        expect(page.get_by_role('link', name='查看事务', exact=True)).to_have_count(3)
        assert len(decisions) == before + 2
        assert all(row['operation'] == 'create' for row in decisions[-2:])
        page.set_viewport_size({'width':1440,'height':1000})
        extra = {**item, 'id':'item-4', 'title':'需匹配已有事务', 'source_id':'12:assignment:4b'}
        items.append(extra)
        actions[extra['id']] = {**action, 'todo':dict(kind='todo',state='pending',target_id=None,business=None,error='',result={}), 'calendar':None, 'reminder':None}
        page.get_by_role('button', name='刷新', exact=True).click()
        page.get_by_role('checkbox', name='选择 需匹配已有事务').check()
        page.get_by_role('button', name='生成事务', exact=False).click()
        expect(page.get_by_role('checkbox', name='选择 需匹配已有事务')).to_be_checked()
        expect(page.get_by_text('1 项事务生成失败', exact=False)).to_be_visible()
        page.get_by_role('checkbox', name='选择 需匹配已有事务').uncheck()
        extra = {**item, 'id':'item-5', 'title':'刷新失败后仍已创建', 'source_id':'12:assignment:5'}
        items.append(extra)
        actions[extra['id']] = {**action, 'todo':dict(kind='todo',state='pending',target_id=None,business=None,error='',result={}), 'calendar':None, 'reminder':None}
        page.get_by_role('button', name='刷新', exact=True).click()
        page.get_by_role('checkbox', name='选择 刷新失败后仍已创建').check()
        before = len(decisions)
        page.get_by_role('button', name='生成事务', exact=False).click()
        expect(page.get_by_text('HTTP 503', exact=False)).to_be_visible()
        expect(page.get_by_role('checkbox', name='选择 刷新失败后仍已创建')).to_be_disabled()
        expect(page.get_by_text('1 项事务生成失败', exact=False)).to_have_count(0)
        assert len(decisions) == before + 1
        assert errors == [], errors
        print('UI briefing: manual batch creation/retry/preferences/scoped authorization/full overview/calendar target/narrow desktop PASS; 390px geometry only')
    finally:
        browser.close()
