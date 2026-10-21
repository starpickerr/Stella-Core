"""Peer business calls through the approved Core channel; no peer data paths."""
import hashlib
import json

from domain.actions import AdapterUnavailable, PeerOutcomeUnknown


class PeerService:
    def __init__(self, kind):
        self.kind = kind
        self.contract = 'stella.tasks@1' if kind == 'todo' else 'stella.calendar@1'

    def _call(self, method, payload, write=False):
        try:
            from stella_host import invoke
        except ImportError:
            raise AdapterUnavailable('Core public service channel unavailable') from None
        key = 'briefing:' + hashlib.sha256(json.dumps([self.contract, method, payload], sort_keys=True).encode()).hexdigest() if write else None
        try:
            result = invoke(self.contract, method, payload, idempotency_key=key)
        except PermissionError:
            raise
        except (RuntimeError, OSError) as exc:
            if not write:
                raise AdapterUnavailable('Core public service unavailable') from exc
            raise
        if result['status'] == 'failed':
            error = result.get('error') or {}
            if error.get('code') in {'permission_denied','unauthorized','forbidden'}:
                raise PermissionError(error.get('message') or 'peer access denied')
            if error.get('code') == 'not_found':
                raise KeyError(error.get('message'))
            raise ValueError(error.get('message') or 'peer operation failed')
        if result['status'] != 'succeeded':
            raise PeerOutcomeUnknown('peer operation outcome is unknown; retry with the stable operation key')
        return result.get('value')

    def list_todos(self, include_completed=False):
        return self._call('list_todos', {'include_completed': include_completed})

    def list_events(self):
        return self._call('list_events', {})

    def get_todo(self, todo_id):
        return self._call('get_todo', {'todo_id': todo_id})

    def get_event(self, event_id):
        return self._call('get_event', {'id': event_id})

    def has_source_tombstone(self, keys):
        result = self._call('has_source_tombstone', {'source_keys': sorted(keys)})
        return result['tombstoned'] if isinstance(result, dict) else result

    def find_briefing_sources(self, keys):
        return self._call('find_briefing_sources', {'source_keys': sorted(keys)})

    def create_todo(self, payload, *, _briefing_key=None):
        body = dict(payload)
        if _briefing_key:
            body['_briefing_key'] = _briefing_key
        return self._call('create_todo', {'payload': body}, True)

    def create_event(self, payload, *, _briefing_key=None):
        body = dict(payload)
        if _briefing_key:
            body['_briefing_key'] = _briefing_key
        return self._call('create_event', body, True)

    def update_todo(self, todo_id, payload):
        return self._call('update_todo', {'todo_id': todo_id, 'payload': payload}, True)

    def sync_briefing_facts(self, target_id, changes, baseline, force=False):
        payload = {'changes': changes, 'baseline': baseline, 'force': force,
                   ('todo_id' if self.kind == 'todo' else 'id'): target_id}
        result = self._call('sync_briefing_facts', payload, True)
        return tuple(result) if self.kind == 'todo' else (result['event'], result['conflicts'])
