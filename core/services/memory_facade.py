"""Agent/entry adapter for the Memory public service; no direct file or index access."""
from contextvars import copy_context
from copy import deepcopy
import threading

from common.log import logger
from core.plugins.lifecycle import domain_data_handle
from core.plugins.caller import plugin_user_id
from core.services.memory_gateway import invoke_memory


def plugin_available(plugin_id, user_id=None):
    from core.plugins.management import default_store
    store = default_store()
    user = user_id or plugin_user_id()
    if not store.has_instance(plugin_id, user):
        return False
    return store.instance(plugin_id, user)['intent'] == 'enabled' and store.runtime_state(plugin_id, user) not in {'maintenance', 'draining', 'failed'}


class MemoryPort:
    def __init__(self, workspace_root=None, *, identity=None):
        self.identity = identity
        self.model = None
        self.flush_manager = self
        self._last_flush_thread = None

    def is_available(self):
        return plugin_available('stella.memory', self.identity.user_id if self.identity else None)

    def _call(self, method, **params):
        from common.runtime_identity import current_identity, use_identity
        from contextlib import nullcontext
        current = current_identity()
        if self.identity is not None:
            if current.user_id and current.user_id != self.identity.user_id:
                raise PermissionError('memory port belongs to another user')
            if current.agent_id and self.identity.agent_id and current.agent_id != self.identity.agent_id:
                raise PermissionError('memory port belongs to another Agent')
        with use_identity(self.identity) if self.identity is not None and current.agent_id is None else nullcontext():
            return self._invoke(method, **params)

    def _invoke(self, method, **params):
        from models.plugin_service import bind_model, reset_model
        token = bind_model(self.model)
        try:
            handle = domain_data_handle('stella.memory', plugin_user_id())
            result = invoke_memory(method, params, data_dir=handle['dataDir'])
            if result['status'] != 'succeeded':
                raise RuntimeError((result.get('error') or {}).get('message') or 'memory plugin unavailable')
            return result.get('value')
        finally:
            reset_model(token)

    def list_files(self, **params):
        return self._call('list_files', **params)

    def get_content(self, filename, category='memory'):
        return self._call('get_content', filename=filename, category=category)

    def dispatch(self, action, payload):
        return self._call('dispatch', action=action, payload=payload)

    def read(self, **params):
        return self._call('read', **params)

    def search(self, **params):
        return self._call('search', **params)['results']

    def get_status(self):
        return self._call('get_status')

    def flush_memory(self, messages, user_id=None, reason='threshold', max_messages=10, context_summary_callback=None):
        if not self.is_available():
            return False
        values = deepcopy(dict(messages=messages, reason=reason, max_messages=max_messages))
        context = copy_context()
        def run():
            try:
                result = self._call('flush_memory', **values)
                if result.get('summary') and context_summary_callback:
                    context_summary_callback(result['summary'])
            except Exception as exc:
                logger.warning('[Memory] plugin flush unavailable: %s', exc)
        self._last_flush_thread = threading.Thread(target=lambda: context.run(run), daemon=True, name='plugin-memory-flush')
        self._last_flush_thread.start()
        return True

    def create_daily_summary(self, messages, user_id=None):
        return self.flush_memory(messages, reason='daily_summary', max_messages=0)

    def write_daily_summary(self, summary, user_id=None, reason='context_compaction'):
        try:
            return self._call('write_daily_summary', summary=summary, reason=reason)
        except Exception as exc:
            logger.warning('[Memory] summary persistence unavailable: %s', exc)
            return False

    def deep_dream(self, **params):
        if not self.is_available():
            return False
        return self._call('deep_dream', **params).get('dreamed', False)
