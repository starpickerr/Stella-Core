"""User decisions, scoped authorizations and durable business receipts."""
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import pytest
from agent.briefing.service import BriefingService
from agent.briefing.store import BriefingStore
from agent.todos.service import TodoService
from agent.calendar.service import CalendarService


@pytest.fixture
def env(tmp_path):
    from agent.scheduler.store import TaskStore
    todos = TodoService(tmp_path/'todos.db', tmp_path/'calendar.db', scheduler_store=TaskStore(str(tmp_path/'scheduler.json')))
    calendar = CalendarService(tmp_path/'calendar.db')
    service = BriefingService(BriefingStore(tmp_path/'briefing.db'))
    from agent.briefing.actions import BriefingActions
    actions = BriefingActions(service.store, todos=todos, calendar=calendar)
    return service, actions, todos, calendar


def publish(env, *, day='2026-10-08', source_id='12:assignment:4', section='action', payload=None, source='elearning'):
    service, actions, _, _ = env
    briefing = service.start_briefing(briefing_date=day)
    item, _ = service.upsert_source_item(dict(source=source, account_id='campus', source_id=source_id,
        title='Algorithms · Assignment 4', occurred_at=day+'T08:00:00Z',
        payload=payload or {'resource_type':'assignment','course_id':'12','due_at':'2026-10-29T15:59:00Z'}))
    detail=service.complete_briefing(briefing.id,dict(status='completed',items=[dict(source_item_id=item.id,section=section,score=80)]))
    actions.prepare(detail)
    return detail, detail['items'][0]


def test_new_assignment_suggests_without_unauthorized_side_effects(env):
    detail,item=publish(env)
    _,actions,todos,calendar=env
    actions.sync(detail,'todo')
    actions.sync(detail,'calendar')
    assert todos.list_todos() == []
    assert calendar.list_events('2026-10-01T00:00:00Z','2026-11-01T00:00:00Z') == []
    view=actions.view([item])[item.id]
    assert view['category']=='needs_action'
    assert view['todo']['state']=='pending'
    assert view['calendar'] is None


def test_confirm_create_idempotent_and_source_updates_preserve_plan(env):
    detail,item=publish(env)
    _,actions,todos,_=env
    receipt=actions.decide(item.id,dict(operation='create',kind='todo',title='My homework',planned_on='2026-10-20'))
    assert receipt['state']=='succeeded'
    todo_id=receipt['target_id']
    assert actions.decide(item.id,dict(operation='create',kind='todo'))['target_id']==todo_id
    todos.update_todo(todo_id,{'planned_on':'2026-10-21'})
    updated,new=publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-28T15:59:00Z','submission_status':'submitted'})
    actions.sync(updated,'todo')
    row=todos.get_todo(todo_id)
    assert row['planned_on']=='2026-10-21'
    assert row['due_on']=='2026-10-28'
    assert row['title']=='My homework'
    assert row['status']=='todo'
    assert len(todos.list_todos())==1
    assert actions.view([new])[new.id]['facts']['submission_status']=='submitted'


def test_user_deadline_conflict_requires_decision(env):
    _,item=publish(env)
    _,actions,todos,_=env
    receipt=actions.decide(item.id,dict(operation='create',kind='todo'))
    todos.update_todo(receipt['target_id'],dict(due_on='2026-10-30'))
    detail,new=publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-28T15:59:00Z'})
    actions.sync(detail,'todo')
    assert actions.view([new])[new.id]['todo']['state']=='conflict'
    assert todos.get_todo(receipt['target_id'])['due_on']=='2026-10-30'
    actions.decide(new.id,dict(operation='confirm_update',kind='todo'))
    assert todos.get_todo(receipt['target_id'])['due_on']=='2026-10-28'


def test_link_existing_unlink_and_delete_do_not_recreate(env):
    detail,item=publish(env)
    _,actions,todos,_=env
    todo=todos.create_todo({'title':'Existing'})
    actions.decide(item.id,dict(operation='link',kind='todo',target_id=todo['id']))
    actions.decide(item.id,dict(operation='unlink',kind='todo'))
    actions.sync(detail,'todo')
    assert len(todos.list_todos())==1
    assert actions.view([item])[item.id]['todo']['state']=='detached'
    with pytest.raises(ValueError, match='explicit'):
        actions.decide(item.id,dict(operation='create',kind='todo'))
    actions.decide(item.id,dict(operation='link',kind='todo',target_id=todo['id']))
    todos.delete_todo(todo['id'])
    actions.sync(detail,'todo')
    assert todos.list_todos()==[]
    assert actions.view([item])[item.id]['todo']['state']=='deleted'


def test_scoped_rule_automates_only_authorized_type_and_can_be_revoked(env):
    detail,item=publish(env)
    _,actions,todos,_=env
    rule=actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='todo',mode='auto',course_id='12'))
    actions.sync(detail,'todo')
    assert len(todos.list_todos())==1
    other,_=publish(env,source_id='13:assignment:4',payload={'resource_type':'assignment','course_id':'13'})
    actions.sync(other,'todo')
    assert len(todos.list_todos())==1
    actions.delete_rule(rule['id'])
    assert actions.list_rules()==[]


def test_meeting_creation_needs_actual_times_and_confirmation(env):
    detail,item=publish(env,source='email',source_id='invite',section='fyi',payload={'information_type':'meeting','start_at':'2026-10-10T09:00:00+08:00','end_at':'2026-10-10T10:00:00+08:00'})
    _,actions,_,calendar=env
    actions.sync(detail,'calendar')
    assert calendar.list_events('2026-10-01T00:00:00Z','2026-11-01T00:00:00Z')==[]
    receipt=actions.decide(item.id,dict(operation='create',kind='calendar'))
    assert calendar.get_event(receipt['target_id'])['title']==item.title
    _,deadline=publish(env)
    with pytest.raises(ValueError,match='start'):
        actions.decide(deadline.id,dict(operation='create',kind='calendar'))


def test_failure_retry_completion_history_and_reclassification(env, monkeypatch):
    detail,item=publish(env)
    service,actions,todos,_=env
    original=todos.create_todo
    def fail(*args,**kwargs): raise RuntimeError('temporary failure')
    monkeypatch.setattr(todos,'create_todo',fail)
    failed=actions.decide(item.id,dict(operation='create',kind='todo'))
    assert failed['state']=='failed' and 'temporary failure' in failed['error']
    monkeypatch.setattr(todos,'create_todo',original)
    receipt=actions.decide(item.id,dict(operation='retry',kind='todo'))
    todos.complete_todo(receipt['target_id'],True)
    assert actions.view([item])[item.id]['todo']['business']['status']=='completed'
    original_snapshot=service.get_revision(detail['briefing'].id,1)
    updated,new=publish(env,day='2026-10-09',section='fyi')
    actions.sync(updated,'todo')
    assert todos.get_todo(receipt['target_id'])['status']=='completed'
    assert service.get_revision(detail['briefing'].id,1)['items']==original_snapshot['items']
    assert asdict(item)['status']=='undo'


def test_concurrent_confirmations_create_one_business_object(env):
    _,item=publish(env)
    _,actions,todos,_=env
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:actions.decide(item.id,dict(operation='create',kind='todo')),range(4)))
    assert len({row['target_id'] for row in results})==1
    assert len(todos.list_todos())==1


def test_legacy_objects_are_adopted_and_user_deadlines_are_protected(env):
    _,item=publish(env)
    _,actions,todos,_=env
    import json
    key=json.dumps([item.source,item.account_id,item.source_id],ensure_ascii=False,separators=(',',':'))
    todos._upsert_sourced_todo(key,item,item.payload['due_at'],item.briefing_id)
    old=todos.list_todos()[0]
    todos.update_todo(old['id'],dict(due_on='2026-10-30',planned_on='2026-10-20'))
    detail,new=publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-28T15:59:00Z'})
    actions.sync(detail,'todo')
    assert len(todos.list_todos())==1
    assert actions.view([new])[new.id]['todo']['target_id']==old['id']
    assert actions.view([new])[new.id]['todo']['state']=='conflict'
    assert todos.get_todo(old['id'])['due_on']=='2026-10-30'


def test_grade_and_assignment_share_entity_without_completing_task(env):
    _,item=publish(env)
    _,actions,todos,_=env
    created=actions.decide(item.id,dict(operation='create',kind='todo'))
    detail,grade=publish(env,day='2026-10-09',source_id='12:grade:4',section='fyi',payload={'resource_type':'grade','course_id':'12','submission_status':'graded','score':100,'due_at':None})
    actions.sync(detail,'todo')
    view=actions.view([grade])[grade.id]
    assert view['todo']['target_id']==created['target_id']
    assert view['facts']['score']==100
    assert todos.get_todo(created['target_id'])['status']=='todo'
    assert todos.get_todo(created['target_id'])['due_on']=='2026-10-29'


def test_recovered_business_commit_uses_same_durable_key(env, monkeypatch):
    _,item=publish(env)
    _,actions,todos,_=env
    original=actions._write
    def crash_after_business(db,key,kind,**fields):
        if fields.get('target_id'):
            raise KeyboardInterrupt('crash after business commit')
        return original(db,key,kind,**fields)
    monkeypatch.setattr(actions,'_write',crash_after_business)
    with pytest.raises(KeyboardInterrupt):
        actions.decide(item.id,dict(operation='create',kind='todo'))
    monkeypatch.setattr(actions,'_write',original)
    result=actions.decide(item.id,dict(operation='create',kind='todo'))
    assert result['state']=='succeeded' and len(todos.list_todos())==1


def test_unchanged_cross_day_cards_are_distinct_from_new_changes(env):
    _,first=publish(env)
    _,actions,_,_=env
    _,second=publish(env,day='2026-10-09')
    assert actions.view([first])[first.id]['change_type']=='new'
    assert actions.view([second])[second.id]['change_type']=='unchanged'
    _,third=publish(env,day='2026-10-10',payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-28T15:59:00Z'})
    assert actions.view([third])[third.id]['change_type']=='changed'


def test_delayed_first_seen_source_is_not_lost_by_window(env):
    service,_,_,_=env
    item,_=service.build_source_item(dict(source='email',account_id='campus',source_id='delayed',title='Late notification',occurred_at='2026-10-01T08:00:00Z'))
    service.store.stage_source_items('late',[(item,None)])
    rows=service.store.staged_window_candidates('late','2026-10-07T08:00:00Z','2026-10-08T08:00:00Z',[('email','campus')])
    assert [row[0].source_id for row in rows]==['delayed']


def test_agent_decision_uses_same_service_receipt(env):
    _,item=publish(env)
    service,actions,todos,_=env
    service._actions=actions
    from agent.tools.briefing.briefing_tool import BriefingTool
    result=BriefingTool(service=service).execute(dict(action='decide',item_id=item.id,decision={'operation':'create','kind':'todo'}))
    assert result.status == 'success'
    assert len(todos.list_todos())==1
    assert service.get_briefing(item.briefing_id)['actions'][item.id]['todo']['target_id']==todos.list_todos()[0]['id']


def test_action_mutations_need_security_write_capability():
    from agent.permission.gateway import _LOCAL_ACTIONS
    assert {'decide','authorize','revoke_authorization','set_preferences'} <= _LOCAL_ACTIONS['briefing']
    from agent.permission.gateway import SecurityGateway
    assert not SecurityGateway.check('read-only','briefing',{'action':'decide','decision':{'operation':'create','kind':'todo'}})
    assert not SecurityGateway.check('read-only','briefing',{'action':'authorize'})
    assert SecurityGateway.check('read-only','briefing',{'action':'overview'})


def test_confirmed_deadline_override_survives_sync_and_reports_future_conflict(env):
    detail, item = publish(env)
    _, actions, todos, _ = env
    created = actions.decide(item.id, dict(operation='create', kind='todo', due_at='2026-10-30T15:59:00Z'))
    actions.sync(detail, 'todo')
    assert todos.get_todo(created['target_id'])['due_on'] == '2026-10-30'
    updated, new = publish(env, day='2026-10-09', payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-28T15:59:00Z'})
    actions.sync(updated, 'todo')
    assert todos.get_todo(created['target_id'])['due_on'] == '2026-10-30'
    assert actions.view([new])[new.id]['todo']['state'] == 'conflict'


def test_removing_source_deadline_clears_only_untouched_fields(env):
    _, item = publish(env)
    _, actions, todos, _ = env
    created = actions.decide(item.id, dict(operation='create',kind='todo'))
    updated, _ = publish(env, day='2026-10-09', payload={'resource_type':'assignment','course_id':'12','due_at':None})
    actions.sync(updated, 'todo')
    assert todos.get_todo(created['target_id'])['due_on'] is None
    assert todos.get_todo(created['target_id'])['due_time'] is None


def test_deleted_legacy_source_is_not_recreated_under_new_identity(env):
    import json
    detail, item = publish(env)
    _, actions, todos, _ = env
    key = json.dumps([item.source,item.account_id,item.source_id],ensure_ascii=False,separators=(',',':'))
    todos._upsert_sourced_todo(key,item,item.payload['due_at'],item.briefing_id)
    todos.delete_todo(todos.list_todos()[0]['id'])
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='todo',mode='auto'))
    actions.sync(detail, 'todo')
    assert todos.list_todos() == []
    assert actions.view([item])[item.id]['todo']['state'] == 'deleted'


def test_ai_email_meeting_times_are_suggested_but_never_automated(env):
    from agent.briefing.actions import facts_for
    _, item = publish(env, source='email', payload={'body_available':True}, section='fyi')
    facts = facts_for(item, {'information_type':'meeting','calendar':{'start_at':'2026-10-10T09:00:00+08:00','end_at':'2026-10-10T10:00:00+08:00'}})
    assert facts['start_at'] == '2026-10-10T09:00:00+08:00'
    assert facts['time_origin'] == 'ai_inference'


def test_explicit_options_on_existing_target_are_rejected_truthfully(env):
    _, item = publish(env)
    _, actions, _, _ = env
    actions.decide(item.id, dict(operation='create',kind='todo'))
    with pytest.raises(ValueError, match='linked'):
        actions.decide(item.id, dict(operation='create',kind='todo',title='Different title'))


def test_reminder_receipt_exposes_scheduler_failure_and_retry(env, monkeypatch):
    _, item = publish(env)
    _, actions, todos, _ = env
    created = actions.decide(item.id, dict(operation='create',kind='todo'))
    def fail(*args, **kwargs):
        raise RuntimeError('scheduler temporarily unavailable')
    monkeypatch.setattr('agent.todos.service.sync_task', fail)
    result = actions.decide(item.id, dict(operation='remind',kind='reminder',remind_at='2099-10-28T08:00:00Z'))
    assert result['state'] == 'failed'
    assert result['target_id'] == created['target_id']
    assert 'scheduler' in result['error']
    monkeypatch.undo()
    assert actions.decide(item.id, dict(operation='retry',kind='reminder'))['state'] == 'succeeded'


def test_cross_source_explicit_link_does_not_overwrite_existing_deadline(env):
    _, item = publish(env)
    _, actions, todos, _ = env
    existing = todos.create_todo(dict(title='Already planned',due_on='2026-10-30',due_time='23:59'))
    actions.decide(item.id, dict(operation='link',kind='todo',target_id=existing['id']))
    detail, _ = publish(env,day='2026-10-09')
    actions.sync(detail,'todo')
    assert todos.get_todo(existing['id'])['due_on'] == '2026-10-30'


def test_calendar_override_survives_source_sync(env):
    detail, item = publish(env,source='email',section='fyi',payload={'information_type':'meeting','start_at':'2026-10-10T09:00:00+08:00','end_at':'2026-10-10T10:00:00+08:00'})
    _, actions, _, calendar = env
    created = actions.decide(item.id,dict(operation='create',kind='calendar',start_at='2026-10-10T11:00:00+08:00',end_at='2026-10-10T12:00:00+08:00'))
    actions.sync(detail,'calendar')
    assert calendar.get_event(created['target_id'])['start_at'] == '2026-10-10T03:00:00+00:00'


def test_explicit_reminder_rule_creates_scheduler_task_without_calendar(env):
    detail, item = publish(env,payload={'resource_type':'assignment','course_id':'12','due_at':'2099-10-29T15:59:00Z'})
    _, actions, todos, calendar = env
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='todo',mode='auto'))
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='reminder',mode='auto',reminder_minutes=60))
    actions.sync(detail,'todo')
    task = todos.list_todos()[0]
    assert task['remind_at'] == '2099-10-29T14:59:00+00:00'
    assert actions.view([item])[item.id]['reminder']['state'] == 'succeeded'
    assert todos.scheduler_store.get_task(task['scheduler_task_id'])['linked_todo_id'] == task['id']
    assert calendar.list_events() == []


def test_similar_existing_business_needs_user_matching_instead_of_auto_duplicate(env):
    detail, item = publish(env)
    _, actions, todos, _ = env
    existing = todos.create_todo({'title':item.title})
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='todo',mode='auto'))
    actions.sync(detail,'todo')
    assert [row['id'] for row in todos.list_todos()] == [existing['id']]
    assert actions.view([item])[item.id]['todo']['state'] == 'pending'


def test_sync_rule_can_require_confirmation_for_new_facts(env):
    _, item = publish(env)
    _, actions, todos, _ = env
    created = actions.decide(item.id,dict(operation='create',kind='todo'))
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='sync',mode='suggest'))
    detail, new = publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-28T15:59:00Z'})
    actions.sync(detail,'todo')
    assert todos.get_todo(created['target_id'])['due_on'] == '2026-10-29'
    assert actions.view([new])[new.id]['todo']['state'] == 'conflict'
    actions.decide(new.id,dict(operation='confirm_update',kind='todo'))
    assert todos.get_todo(created['target_id'])['due_on'] == '2026-10-28'


def test_complete_overview_tracks_prior_days_without_generating_or_projecting(env):
    _, first = publish(env)
    service, actions, todos, _ = env
    service._actions = actions
    actions.decide(first.id,dict(operation='create',kind='todo'))
    detail, second = publish(env, day='2026-10-09',source_id='13:assignment:5',payload={'resource_type':'assignment','course_id':'13'})
    before = len(service.store.list_revisions(detail['briefing'].id))
    result = service.get_overview()
    assert {row.id for row in result['items']} == {first.id,second.id}
    assert len(todos.list_todos()) == 1
    assert len(service.store.list_revisions(detail['briefing'].id)) == before


def test_email_thread_uses_stable_entity_and_keeps_latest_source_facts(env):
    from agent.briefing.actions import entity_key
    _, first = publish(env,source='email',source_id='<message-1>')
    first.thread_id = '<root-message>'
    _, second = publish(env,day='2026-10-09',source='email',source_id='<message-2>')
    second.thread_id = '<root-message>'
    assert entity_key(first) == entity_key(second)


def test_automatic_retry_recovers_business_commit_before_matching_guard(env, monkeypatch):
    detail, item = publish(env)
    _, actions, todos, _ = env
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='todo',mode='auto'))
    original = actions._write
    def crash(db, key, kind, **fields):
        if fields.get('target_id'):
            raise KeyboardInterrupt('interrupted after business commit')
        return original(db,key,kind,**fields)
    monkeypatch.setattr(actions,'_write',crash)
    with pytest.raises(KeyboardInterrupt):
        actions.sync(detail,'todo')
    monkeypatch.setattr(actions,'_write',original)
    actions.sync(detail,'todo')
    assert len(todos.list_todos()) == 1
    assert actions.view([item])[item.id]['todo']['target_id'] == todos.list_todos()[0]['id']


def test_crash_recovery_does_not_claim_new_source_deadline_was_applied(env, monkeypatch):
    detail, _ = publish(env)
    _, actions, todos, _ = env
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='todo',mode='auto'))
    original = actions._write
    def crash(db, key, kind, **fields):
        if fields.get('target_id'):
            raise KeyboardInterrupt('interrupted after business commit')
        return original(db,key,kind,**fields)
    monkeypatch.setattr(actions,'_write',crash)
    with pytest.raises(KeyboardInterrupt):
        actions.sync(detail,'todo')
    monkeypatch.setattr(actions,'_write',original)
    updated, new = publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':'2026-10-30T15:59:00Z'})
    actions.sync(updated,'todo')
    receipt = actions.view([new])[new.id]['todo']
    assert len(todos.list_todos()) == 1
    assert receipt['state'] == 'conflict'
    assert receipt['business']['due_on'] == '2026-10-29'
    actions.decide(new.id,dict(operation='confirm_update',kind='todo'))
    assert todos.get_todo(receipt['target_id'])['due_on'] == '2026-10-30'


def test_inferred_meeting_time_change_exposes_confirmation(env):
    _, actions, _, calendar = env
    detail, item = publish(env,source='email',source_id='<meeting>',payload={'information_type':'meeting'})
    detail['mail'] = [dict(id=item.source_item_id,decision={'information_type':'meeting','calendar':{'start_at':'2026-10-29T01:00:00Z','end_at':'2026-10-29T02:00:00Z'}})]
    actions.prepare(detail)
    created = actions.decide(item.id,dict(operation='create',kind='calendar'))
    updated, new = publish(env,source='email',source_id='<meeting>',day='2026-10-09',payload={'information_type':'meeting'})
    updated['mail'] = [dict(id=new.source_item_id,decision={'information_type':'meeting','calendar':{'start_at':'2026-10-30T01:00:00Z','end_at':'2026-10-30T02:00:00Z'}})]
    actions.sync(updated,'calendar')
    assert actions.view([new])[new.id]['calendar']['state'] == 'conflict'
    assert calendar.get_event(created['target_id'])['start_at'] == '2026-10-29T01:00:00+00:00'
    actions.decide(new.id,dict(operation='confirm_update',kind='calendar'))
    assert calendar.get_event(created['target_id'])['start_at'] == '2026-10-30T01:00:00+00:00'


def test_failed_source_reminder_cancellation_can_be_retried(env, monkeypatch):
    detail, item = publish(env,payload={'resource_type':'assignment','due_at':'2099-10-29T15:59:00Z'})
    _, actions, todos, _ = env
    actions.decide(item.id,dict(operation='create',kind='todo'))
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='reminder',mode='auto'))
    actions.sync(detail,'todo')
    task_id = todos.list_todos()[0]['scheduler_task_id']
    original = todos.scheduler_store.delete_task
    def fail(*args, **kwargs):
        raise RuntimeError('offline cancellation')
    monkeypatch.setattr(todos.scheduler_store,'delete_task',fail)
    updated, new = publish(env,day='2026-10-09',payload={'resource_type':'assignment','due_at':None})
    actions.sync(updated,'todo')
    assert actions.view([new])[new.id]['reminder']['state'] == 'failed'
    monkeypatch.setattr(todos.scheduler_store,'delete_task',original)
    receipt = actions.decide(new.id,dict(operation='retry',kind='reminder'))
    assert receipt['state'] == 'succeeded'
    assert todos.scheduler_store.get_task(task_id) is None


def test_email_thread_adopts_legacy_message_key(env):
    import json
    detail, item = publish(env,source='email',source_id='<message>')
    _, actions, todos, _ = env
    item.thread_id = '<root>'
    key = json.dumps([item.source,item.account_id,item.source_id],separators=(',',':'))
    todos._upsert_sourced_todo(key,item,item.payload['due_at'],item.briefing_id)
    old = todos.list_todos()[0]
    actions.sync(detail,'todo')
    assert actions.view([item])[item.id]['todo']['target_id'] == old['id']
    assert len(todos.list_todos()) == 1


def test_user_cleared_auto_reminder_is_not_reinstated_on_deadline_change(env):
    detail, item = publish(env,payload={'resource_type':'assignment','course_id':'12','due_at':'2099-10-29T15:59:00Z'})
    _, actions, todos, _ = env
    created = actions.decide(item.id,dict(operation='create',kind='todo'))
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='reminder',mode='auto',reminder_minutes=60))
    actions.sync(detail,'todo')
    todos.update_todo(created['target_id'], {'remind_at':None})
    updated, _ = publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':'2099-10-30T15:59:00Z'})
    actions.sync(updated,'todo')
    assert todos.get_todo(created['target_id'])['remind_at'] is None
    assert todos.scheduler_store.get_task('todo-reminder:'+created['target_id']) is None


def test_removed_source_deadline_cancels_only_source_owned_reminder(env):
    detail, item = publish(env,payload={'resource_type':'assignment','course_id':'12','due_at':'2099-10-29T15:59:00Z'})
    _, actions, todos, _ = env
    created = actions.decide(item.id,dict(operation='create',kind='todo'))
    actions.save_rule(dict(source='elearning',account_id='campus',information_type='assignment',kind='reminder',mode='auto',reminder_minutes=60))
    actions.sync(detail,'todo')
    updated, _ = publish(env,day='2026-10-09',payload={'resource_type':'assignment','course_id':'12','due_at':None})
    actions.sync(updated,'todo')
    assert todos.get_todo(created['target_id'])['remind_at'] is None
    assert todos.scheduler_store.get_task('todo-reminder:'+created['target_id']) is None


def test_latest_selected_thread_source_updates_facts_independently_of_card_priority(env):
    detail, item = publish(env,source='email',source_id='<root>',payload={'information_type':'meeting','start_at':'2026-10-10T09:00:00+08:00','end_at':'2026-10-10T10:00:00+08:00'})
    _, actions, _, _ = env
    detail['mail'] = [dict(id='latest-source',source='email',account_id='campus',source_id='<reply>',thread_id='<root>',
        title='Meeting rescheduled',occurred_at='2026-10-09T08:00:00Z',category='selected',metadata={'information_type':'meeting','start_at':'2026-10-11T09:00:00+08:00','end_at':'2026-10-11T10:00:00+08:00'},
        decision={'section':'fyi','category':'status_update'})]
    actions.prepare(detail)
    assert actions.view([item])[item.id]['facts']['start_at'] == '2026-10-11T09:00:00+08:00'
