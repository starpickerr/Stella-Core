"""Durable suggestions and scoped decisions, shared by UI, Agent and outbox.

The briefing database serializes decisions. Business writes use a stable key so
that retrying after a crash between databases recovers the same target. Facts
and snapshots remain separate from user plans and completion state.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


CATEGORIES = {'needs_action', 'attention', 'status_update', 'other'}
KINDS = {'todo', 'calendar', 'reminder'}
OPERATIONS = {'create', 'link', 'unlink', 'ignore', 'defer', 'keep', 'retry', 'confirm_update', 'keep_current', 'remind'}
class PeerOutcomeUnknown(RuntimeError):
    side_effects = 'unknown'


class AdapterUnavailable(RuntimeError):
    """Todo/calendar adapters are host-side; the plugin worker cannot reach them."""


DEFAULT_PREFERENCES = {'show_low_priority': True, 'show_ongoing': True, 'reminder_frequency': 'daily', 'summary_detail': 'brief', 'important_types': []}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _dict(item):
    return asdict(item) if is_dataclass(item) else vars(item) if not isinstance(item, dict) else item


def _instant(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('time must include timezone')
    return dt


def entity_key(item):
    """Native assignment and grade records share the same assignment identity."""
    row = _dict(item)
    payload = row.get('payload') or {}
    native = payload.get('entity_id') or (row.get('thread_id') if row['source'] == 'email' else None) or row['source_id']
    if row['source'] == 'elearning' and payload.get('resource_type') in {'assignment', 'grade'}:
        native = str(native).replace(':grade:', ':assignment:')
    return _json([row['source'], row['account_id'], str(native)])


def facts_for(item, decision=None):
    row = _dict(item)
    payload = row.get('payload') or {}
    decision = decision or {}
    facts = {key: payload[key] for key in ('due_at', 'start_at', 'end_at', 'submission_status', 'score', 'grade', 'workflow_state') if key in payload}
    calendar = decision.get('calendar') or {}
    if isinstance(calendar, dict) and calendar.get('start_at') and (payload.get('information_type') or decision.get('information_type')) == 'meeting':
        for key in ('start_at', 'end_at'):
            if key in calendar and key not in facts:
                facts[key] = calendar[key]
        facts['time_origin'] = 'ai_inference'
    else:
        facts['time_origin'] = 'source'
    facts['url'] = row.get('url', '')
    facts['information_type'] = payload.get('information_type') or payload.get('resource_type') or decision.get('information_type') or ('action' if row.get('section') == 'action' else 'information')
    facts['course_id'] = str(payload.get('course_id') or '')
    return facts


def todo_due(facts):
    if not facts.get('due_at'):
        return {'due_on': None, 'due_time': None} if 'due_at' in facts else {}
    dt = _instant(facts['due_at']).astimezone(ZoneInfo('Asia/Shanghai'))
    return {'due_on': dt.date().isoformat(), 'due_time': dt.strftime('%H:%M'), 'timezone': 'Asia/Shanghai'}


class BriefingActions:
    def __init__(self, store, todos=None, calendar=None):
        self.store = store
        self._todos = todos
        self._calendar = calendar
        with store._conn() as db:
            db.executescript(Path(__file__).with_suffix('.sql').read_text())
            db.execute('BEGIN IMMEDIATE')
            columns = {row[1] for row in db.execute('PRAGMA table_info(briefing_action_rules)')}
            if 'reminder_minutes' not in columns:
                db.execute('ALTER TABLE briefing_action_rules ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 1440')

    @property
    def todos(self):
        if self._todos is None:
            raise AdapterUnavailable("todo adapter is not available inside the briefing plugin worker")
        return self._todos

    @property
    def calendar(self):
        if self._calendar is None:
            raise AdapterUnavailable("calendar adapter is not available inside the briefing plugin worker")
        return self._calendar

    def require_adapters(self, operation):
        if self._todos is None or self._calendar is None:
            raise AdapterUnavailable(
                f"{operation} needs host todo/calendar adapters; not available inside the plugin worker")

    def _service(self, kind):
        return self.todos if kind in {'todo', 'reminder'} else self.calendar

    def prepare(self, detail):
        decisions = {row['id']: row.get('decision') or {} for row in detail.get('mail', [])}
        with self.store._conn() as db:
            db.execute('BEGIN IMMEDIATE')
            for item in detail.get('items', []):
                row = dict(_dict(item))
                key = entity_key(item)
                related = []
                for snapshot in detail.get('mail', []):
                    if snapshot.get('category') != 'selected':
                        continue
                    candidate = {**snapshot, 'payload':snapshot.get('metadata') or {}, 'section':snapshot.get('decision', {}).get('section', row['section'])}
                    if entity_key(candidate) == key:
                        related.append(candidate)
                for candidate in sorted(related, key=lambda value: _instant(value['occurred_at'])):
                    if _instant(candidate['occurred_at']) < _instant(row['occurred_at']):
                        continue
                    row.update(title=candidate.get('title') or row['title'], occurred_at=candidate['occurred_at'],
                               source_item_id=candidate['id'], payload={**(row.get('payload') or {}), **candidate['payload']})
                facts = facts_for(row, decisions.get(row.get('source_item_id')))
                signature = hashlib.sha256(_json({'facts': facts, 'title': row['title']}).encode()).hexdigest()
                old = db.execute('SELECT * FROM briefing_entities WHERE entity_key=?', (key,)).fetchone()
                category = decisions.get(row.get('source_item_id'), {}).get('category')
                if category not in CATEGORIES:
                    category = 'status_update' if facts.get('submission_status') in {'submitted', 'graded'} or facts['information_type'] == 'grade' else 'needs_action' if row['section'] == 'action' else 'attention'
                if facts['information_type'] in {'file', 'material', 'competition', 'announcement'}:
                    category = 'other' if row['section'] != 'action' else 'attention'
                if old and facts['information_type'] == 'grade':
                    previous_facts = json.loads(old['facts'])
                    facts = {**previous_facts, **{k:v for k,v in facts.items() if v is not None}}
                    signature = hashlib.sha256(_json({'facts':facts,'title':row['title']}).encode()).hexdigest()
                change = 'new' if old is None else 'unchanged' if old['fingerprint'] == signature else 'changed'
                if old is None or _instant(row['occurred_at']) >= _instant(old['occurred_at']):
                    db.execute('''INSERT INTO briefing_entities VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(entity_key) DO UPDATE SET title=excluded.title,facts=excluded.facts,
                        category=excluded.category,occurred_at=excluded.occurred_at,fingerprint=excluded.fingerprint,
                        information_type=excluded.information_type,updated_at=excluded.updated_at''',
                        (key, row['source'], row['account_id'], facts['information_type'], facts['course_id'], row['title'], _json(facts), category, row['occurred_at'], signature, _now()))
                db.execute('''INSERT INTO briefing_entity_items VALUES (?,?,?,?) ON CONFLICT(item_id)
                    DO UPDATE SET entity_key=excluded.entity_key,change_type=CASE WHEN snapshot_fingerprint=excluded.snapshot_fingerprint THEN change_type ELSE excluded.change_type END,
                    snapshot_fingerprint=excluded.snapshot_fingerprint''', (row['id'], key, change, signature))
                kinds = ['todo'] if category == 'needs_action' or facts['information_type'] in {'assignment', 'grade'} else []
                if facts.get('start_at') and facts.get('end_at'):
                    kinds.append('calendar')
                for kind in kinds:
                    db.execute('INSERT OR IGNORE INTO briefing_actions(entity_key,kind,updated_at) VALUES (?,?,?)', (key, kind, _now()))

    def list_rules(self):
        with self.store._conn() as db:
            return [dict(row) for row in db.execute('SELECT * FROM briefing_action_rules ORDER BY updated_at DESC')]

    def save_rule(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('rule must be an object')
        values = {key: payload.get(key) for key in ('source', 'account_id', 'information_type', 'kind', 'mode')}
        if any(not isinstance(value, str) or not value or value == '*' or len(value) > 300 for value in values.values()):
            raise ValueError('rule requires an explicit source, account and information type')
        if values['kind'] not in KINDS | {'sync'} or values['mode'] not in {'auto', 'suggest', 'briefing_only'}:
            raise ValueError('invalid rule kind or mode')
        course = payload.get('course_id', '')
        if not isinstance(course, str) or len(course) > 300:
            raise ValueError('invalid course scope')
        minutes = payload.get('reminder_minutes', 1440)
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 43200:
            raise ValueError('reminder_minutes must be between 1 and 43200')
        key = hashlib.sha256(_json([values['source'], values['account_id'], values['information_type'], course, values['kind']]).encode()).hexdigest()
        with self.store._conn() as db:
            db.execute('''INSERT INTO briefing_action_rules(id,source,account_id,information_type,course_id,kind,mode,reminder_minutes,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,reminder_minutes=excluded.reminder_minutes,updated_at=excluded.updated_at''',
                (key, values['source'], values['account_id'], values['information_type'], course, values['kind'], values['mode'], minutes, _now()))
        return next(rule for rule in self.list_rules() if rule['id'] == key)

    def delete_rule(self, rule_id):
        with self.store._conn() as db:
            if db.execute('DELETE FROM briefing_action_rules WHERE id=?', (rule_id,)).rowcount == 0:
                raise KeyError('authorization rule not found')

    def preferences(self, payload=None):
        with self.store._conn() as db:
            row = db.execute('SELECT preferences FROM briefing_preferences WHERE id=1').fetchone()
            current = {**DEFAULT_PREFERENCES, **(json.loads(row[0]) if row else {})}
            if payload is not None:
                if not isinstance(payload, dict) or set(payload) - set(DEFAULT_PREFERENCES):
                    raise ValueError('invalid display preferences')
                for key in ('show_low_priority', 'show_ongoing'):
                    if key in payload and not isinstance(payload[key], bool):
                        raise ValueError('preference must be boolean')
                if payload.get('reminder_frequency', 'daily') not in {'daily', 'changes', 'deadline'} or payload.get('summary_detail', 'brief') not in {'brief', 'full'}:
                    raise ValueError('invalid preference option')
                if 'important_types' in payload and (not isinstance(payload['important_types'], list) or any(not isinstance(v, str) or len(v)>100 for v in payload['important_types'])):
                    raise ValueError('important_types must be strings')
                current.update(payload)
                db.execute('INSERT OR REPLACE INTO briefing_preferences VALUES (1,?)', (_json(current),))
            return current

    @staticmethod
    def _rule(db, entity, kind):
        return db.execute('''SELECT * FROM briefing_action_rules WHERE source=? AND account_id=? AND information_type=?
            AND kind=? AND (course_id='' OR course_id=?) ORDER BY length(course_id) DESC LIMIT 1''',
            (entity['source'], entity['account_id'], entity['information_type'], kind, entity['course_id'])).fetchone()

    def _target(self, action):
        if not action['target_id']:
            return None
        try:
            service = self._service(action['kind'])
            return service.get_event(action['target_id']) if action['kind'] == 'calendar' else service.get_todo(action['target_id'])
        except KeyError:
            return None
        except AdapterUnavailable:
            # Cannot verify the peer object; keep the link rather than report deletion.
            return {'id': action['target_id'], 'unresolved': True}

    def _receipt(self, db, key, kind):
        row = db.execute('SELECT * FROM briefing_actions WHERE entity_key=? AND kind=?', (key, kind)).fetchone()
        if row is None:
            return None
        action = dict(row)
        for field in ('options', 'baseline', 'result'):
            action[field] = json.loads(action[field])
        action['business'] = self._target(action)
        if action['target_id'] and action['business'] is None:
            action['state'] = 'deleted'
        return action

    def view(self, items):
        result = {}
        with self.store._conn() as db:
            for item in items:
                row = _dict(item)
                entity = db.execute('''SELECT e.*,i.change_type FROM briefing_entities e JOIN briefing_entity_items i
                    ON e.entity_key=i.entity_key WHERE i.item_id=?''', (row['id'],)).fetchone()
                if entity is None:
                    continue
                key = entity['entity_key']
                result[row['id']] = {'entity_key': key, 'category': entity['category'], 'information_type': entity['information_type'],
                    'facts': json.loads(entity['facts']), 'change_type': entity['change_type'],
                    **{kind: self._receipt(db, key, kind) for kind in ('todo', 'calendar', 'reminder')}}
        return result

    def _write(self, db, key, kind, **fields):
        fields['updated_at'] = _now()
        for name in ('options', 'baseline', 'result'):
            if name in fields:
                fields[name] = _json(fields[name])
        columns = ','.join(f'{name}=?' for name in fields)
        db.execute(f'UPDATE briefing_actions SET {columns} WHERE entity_key=? AND kind=?', (*fields.values(), key, kind))

    def _baseline(self, business, facts, kind):
        changes = todo_due(facts) if kind == 'todo' else {key: _instant(facts[key]).astimezone(timezone.utc).isoformat() for key in ('start_at', 'end_at') if facts.get(key)}
        return {**business, **changes}

    def _legacy_keys(self, db, key):
        keys = {key}
        rows = db.execute('''SELECT b.source,b.account_id,b.source_id FROM briefing_items b
            JOIN briefing_entity_items i ON i.item_id=b.id WHERE i.entity_key=?''', (key,))
        keys.update(_json([row['source'], row['account_id'], row['source_id']]) for row in rows)
        return keys

    def _was_deleted(self, db, key, kind):
        candidates = self._legacy_keys(db, key)
        # Use public domain methods — do not open peer private tables here.
        return self._service(kind).has_source_tombstone(candidates)

    def _adopt_existing(self, db, entity, kind):
        key = entity['entity_key']
        stable_key = 'entity:' + hashlib.sha256(key.encode()).hexdigest()
        aliases = sorted(self._legacy_keys(db, key) | {stable_key})
        rows = self._service(kind).find_briefing_sources(aliases)
        if len(rows) > 1:
            self._write(db, key, kind, state='pending', result={'operation':'matching_required','candidate_ids':[row['id'] for row in rows]})
            return 'ambiguous'
        if not rows:
            return None
        business = dict(rows[0])
        facts = json.loads(entity['facts'])
        recovered = business['source_key'] == stable_key
        baseline = self._baseline(business, facts, kind) if recovered or business['user_modified'] else business
        result = {'operation':'recovered' if recovered else 'adopted'}
        self._write(db, key, kind, state='succeeded', target_id=business['id'], baseline=baseline, authorization='recovered_link' if recovered else 'legacy_link', result=result, error='')
        return 'adopted'

    def _matching_targets(self, entity, kind):
        service = self._service(kind)
        rows = service.list_todos(include_completed=True) if kind == 'todo' else service.list_events()
        return [row for row in rows if row['title'].strip().casefold() == entity['title'].strip().casefold()]

    def _sync_reminder(self, db, entity):
        rule = self._rule(db, entity, 'reminder')
        task = self._receipt(db, entity['entity_key'], 'todo')
        if not rule or rule['mode'] != 'auto' or not task or not task['business']:
            return
        business = task['business']
        if business['status'] in {'completed', 'cancelled'}:
            return
        key = entity['entity_key']
        facts = json.loads(entity['facts'])
        prior = self._receipt(db, key, 'reminder')
        if prior and prior['state'] in {'ignored', 'deferred', 'briefing_only', 'detached', 'deleted', 'failed', 'conflict'}:
            return
        if prior and business.get('remind_at') != prior['result'].get('remind_at'):
            return
        if not prior and business.get('remind_at'):
            return
        if not facts.get('due_at'):
            if not prior or not prior['authorization'].startswith('rule:'):
                return
            desired = None
        else:
            remind_at = (_instant(facts['due_at']) - timedelta(minutes=rule['reminder_minutes'])).astimezone(timezone.utc)
            if remind_at <= datetime.now(timezone.utc):
                return
            desired = remind_at.isoformat()
        if prior and prior['result'].get('remind_at') == desired:
            return
        db.execute('INSERT OR IGNORE INTO briefing_actions(entity_key,kind,updated_at) VALUES (?, ?, ?)', (key, 'reminder', _now()))
        self._write(db, key, 'reminder', options={'remind_at': desired}, authorization='rule:' + rule['id'])
        self._execute(db, entity, 'reminder')

    def decide(self, item_id, payload):
        if not isinstance(payload, dict) or payload.get('operation') not in OPERATIONS or payload.get('kind', 'todo') not in KINDS:
            raise ValueError('invalid briefing decision')
        kind = payload.get('kind', 'todo')
        operation = payload['operation']
        with self.store._conn() as db:
            db.execute('BEGIN IMMEDIATE')
            entity = db.execute('''SELECT e.* FROM briefing_entities e JOIN briefing_entity_items i
                ON e.entity_key=i.entity_key WHERE i.item_id=?''', (item_id,)).fetchone()
            if entity is None:
                raise KeyError('briefing item has no suggestion; update the briefing first')
            key = entity['entity_key']
            db.execute('INSERT OR IGNORE INTO briefing_actions(entity_key,kind,updated_at) VALUES (?,?,?)', (key, kind, _now()))
            action = self._receipt(db, key, kind)
            if operation in {'ignore', 'defer', 'keep', 'unlink'}:
                state = {'ignore': 'ignored', 'defer': 'deferred', 'keep': 'briefing_only', 'unlink': 'detached'}[operation]
                self._write(db, key, kind, state=state, error='', **({'target_id': None} if operation == 'unlink' else {}))
            elif operation == 'link':
                self.require_adapters('update_action')
                target = payload.get('target_id')
                service = self._service(kind)
                business = service.get_event(target) if kind == 'calendar' else service.get_todo(target)
                facts = json.loads(entity['facts'])
                self._write(db, key, kind, state='succeeded', target_id=business['id'], baseline=self._baseline(business, facts, kind), result={'operation': 'linked', 'source_facts': facts}, authorization='user_confirmation', error='')
            elif operation == 'keep_current':
                business = action['business']
                if business is None:
                    raise ValueError('no linked business object')
                self._write(db, key, kind, state='succeeded', result={'operation': 'kept_current', 'retained_facts': json.loads(entity['facts'])}, error='')
            else:
                self.require_adapters('update_action')
                if action['state'] in {'deleted', 'detached'}:
                    raise ValueError('explicit linking is required after deletion or detachment')
                if operation == 'create' and action['business'] and any(field in payload for field in ('title', 'parent_id', 'planned_on', 'due_at', 'start_at', 'end_at', 'all_day')):
                    raise ValueError('edit the linked object in its business module')
                if operation == 'retry' and action['state'] not in {'failed', 'conflict'}:
                    raise ValueError('only failed actions can be retried')
                options = dict(action['options'])
                options.update({k: payload[k] for k in ('title', 'parent_id', 'planned_on', 'due_at', 'remind_at', 'start_at', 'end_at', 'all_day') if k in payload})
                facts = json.loads(entity['facts'])
                if kind == 'calendar' and operation in {'create', 'retry'} and (not (options.get('start_at') or facts.get('start_at')) or not (options.get('end_at') or facts.get('end_at'))):
                    raise ValueError('calendar creation requires explicit start and end times')
                cancellation_retry = operation == 'retry' and 'remind_at' in action['options'] and action['options']['remind_at'] is None
                if kind == 'reminder' and ((not options.get('remind_at') and not cancellation_retry) or not self._receipt(db,key,'todo') or not self._receipt(db,key,'todo')['business']):
                    raise ValueError('reminder requires a linked task and explicit reminder time')
                self._write(db, key, kind, options=options, operation='remind' if kind == 'reminder' else 'create', authorization='user_confirmation')
                self._execute(db, entity, kind, force=operation == 'confirm_update')
            receipt = self._receipt(db, key, kind)
        if kind != 'todo' and payload.get('remember') is True and receipt['state'] == 'succeeded':
            self.save_rule(dict(source=entity['source'],account_id=entity['account_id'],information_type=entity['information_type'],course_id=entity['course_id'],kind=kind,mode='auto'))
        return receipt

    def _execute(self, db, entity, kind, force=False, propagate=False):
        key = entity['entity_key']
        action = self._receipt(db, key, kind)
        facts = json.loads(entity['facts'])
        options = action['options']
        service = self._service(kind)
        try:
            business = action['business']
            if action['target_id'] and business is None:
                self._write(db,key,kind,state='deleted',error='Linked object was deleted; automatic recreation is disabled')
                return
            if kind == 'reminder':
                task = self._receipt(db,key,'todo')['business']
                business = service.update_todo(task['id'], {'remind_at': options['remind_at']})
                pending = business.get('reminder_sync_pending', False)
                self._write(db,key,kind,state='failed' if pending else 'succeeded',target_id=business['id'],baseline=business,result={'operation':'reminder_pending' if pending else 'reminder_configured','remind_at':business['remind_at']},error=business.get('reminder_sync_error') or ('Reminder delivery configuration pending' if pending else ''))
                return
            if business is None:
                adopted = self._adopt_existing(db, entity, kind)
                if adopted == 'ambiguous':
                    return
                if adopted:
                    action = self._receipt(db, key, kind)
                    business = action['business']
            if business is None:
                if self._was_deleted(db, key, kind):
                    self._write(db, key, kind, state='deleted', error='Previously deleted source object; explicitly link another object')
                    return
                stable_key = 'entity:' + hashlib.sha256(key.encode()).hexdigest()
                if kind == 'todo':
                    data = {'title': options.get('title') or entity['title'], **todo_due({**facts, **({'due_at': options['due_at']} if 'due_at' in options else {})})}
                    data.update({k: options[k] for k in ('parent_id','planned_on','remind_at') if k in options})
                    business = service.create_todo(data, _briefing_key=stable_key)
                else:
                    data = {'title':options.get('title') or entity['title'], 'start_at':options.get('start_at') or facts.get('start_at'), 'end_at':options.get('end_at') or facts.get('end_at'), 'all_day':options.get('all_day',False)}
                    business = service.create_event(data, _briefing_key=stable_key)
                self._write(db,key,kind,state='succeeded',target_id=business['id'],baseline=self._baseline(business, facts, kind),result={'operation':'created','source_facts':facts},error='')
                if kind == 'todo' and options.get('remind_at'):
                    db.execute('INSERT OR IGNORE INTO briefing_actions(entity_key,kind,updated_at) VALUES (?, ?, ?)', (key, 'reminder', _now()))
                    self._write(db, key, 'reminder', target_id=business['id'], options={'remind_at': options['remind_at']}, authorization=action['authorization'])
                    self._execute(db, entity, 'reminder')
                return
            retained = action['result'].get('retained_facts')
            if retained == facts and not force:
                return
            if action['result'].get('source_facts') == facts and not force:
                return
            changes = todo_due(facts) if kind == 'todo' else {k:facts[k] for k in ('start_at','end_at') if k in facts}
            if kind == 'calendar' and facts.get('time_origin') == 'ai_inference' and not force:
                inferred_changes = {field: {'current': business[field], 'source': value}
                                    for field, value in changes.items() if _instant(value) != _instant(business[field])}
                if inferred_changes:
                    self._write(db,key,kind,state='conflict',result={'operation':'confirmation_required','changes':inferred_changes},
                                error='Extracted activity times changed; confirm update or keep current')
                    return
            row, conflicts = service.sync_briefing_facts(business['id'], changes, action['baseline'], force=force)
            self._write(db,key,kind,state='conflict' if conflicts else 'succeeded',baseline=action['baseline'] if conflicts else row,
                result={'operation':'conflict' if conflicts else 'synced','changes':conflicts,'source_facts':facts},error='User fields differ from source; choose confirm update or keep current' if conflicts else '')
        except PeerOutcomeUnknown:
            raise
        except Exception as exc:
            self._write(db,key,kind,state='failed',error=str(exc),result={'operation':'failed'})
            if propagate:
                raise

    def sync(self, detail, consumer):
        if consumer not in {'todo','calendar'}:
            raise ValueError('invalid action consumer')
        self.require_adapters('sync')
        self.prepare(detail)
        keys = {entity_key(item) for item in detail.get('items', [])}
        with self.store._conn() as db:
            db.execute('BEGIN IMMEDIATE')
            for key in keys:
                entity = db.execute('SELECT * FROM briefing_entities WHERE entity_key=?',(key,)).fetchone()
                action = self._receipt(db,key,consumer)
                if action is None or action['state'] in {'ignored','deferred','briefing_only','detached','deleted','failed','conflict'}:
                    continue
                if not action['target_id'] and action['state']=='pending':
                    adopted = self._adopt_existing(db, entity, consumer)
                    if adopted == 'ambiguous':
                        continue
                    if adopted:
                        action = self._receipt(db,key,consumer)
                rule = self._rule(db,entity,consumer)
                sync_rule = self._rule(db,entity,'sync')
                if action['target_id']:
                    if not sync_rule or sync_rule['mode']=='auto':
                        self._execute(db,entity,consumer,propagate=True)
                    elif sync_rule['mode'] == 'suggest' and action['result'].get('source_facts') != json.loads(entity['facts']):
                        self._write(db, key, consumer, state='conflict', error='Your source rule requires confirmation before synchronizing new facts', result={'operation': 'confirmation_required'})
                elif rule and rule['mode']=='auto' and consumer != 'todo':
                    facts = json.loads(entity['facts'])
                    if consumer == 'calendar' and facts.get('time_origin') != 'source':
                        continue
                    matches = self._matching_targets(entity, consumer)
                    if matches:
                        self._write(db, key, consumer, result={'operation':'matching_required','candidate_ids':[row['id'] for row in matches]})
                        continue
                    self._write(db,key,consumer,authorization='rule:'+rule['id'])
                    self._execute(db,entity,consumer,propagate=True)
                elif rule and rule['mode']=='briefing_only':
                    self._write(db,key,consumer,state='briefing_only')
                if consumer == 'todo':
                    self._sync_reminder(db, entity)
