"""Test-only access to the external Briefing owner for SQL faults and legacy seeds.

Production entry points use the RPC facade. No domain implementation is copied
here; store/service/actions below are loaded from the workspace plugin package.
"""
import importlib
import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'stella-plugins-workspace/plugins/briefing/backend/domain'
name = 'stella_briefing_domain_core_tests'
spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[name] = package
spec.loader.exec_module(package)
store_module = importlib.import_module(name + '.store')
service_module = importlib.import_module(name + '.service')
actions_module = importlib.import_module(name + '.actions')
outbox_module = importlib.import_module(name + '.outbox')
BriefingActions = actions_module.BriefingActions
facts_for = actions_module.facts_for
entity_key = actions_module.entity_key
load_schema_sql = store_module.load_schema_sql
briefing_id_for = service_module.briefing_id_for


def _adapters():
    from core.services.calendar_gateway import calendar_plugin_enabled
    from core.services.todos_gateway import todos_plugin_enabled
    from core.services.calendar_facade import CalendarPluginFacade
    from core.services.todos_facade import TodosPluginFacade
    return (TodosPluginFacade() if todos_plugin_enabled() else None,
            CalendarPluginFacade() if calendar_plugin_enabled() else None)


def dispatch_pending(store, limit=20):
    todos, calendar = _adapters()
    return outbox_module.dispatch_pending(store, limit, todos=todos, calendar=calendar)


class BriefingStore(store_module.BriefingStore):
    def dispatch_outbox(self, limit=20):
        return dispatch_pending(self, limit)


class BriefingService(service_module.BriefingService):
    def __init__(self, store=None):
        if store is None:
            from common.state_dir import briefing_db
            store = BriefingStore(briefing_db())
        todos, calendar = _adapters()
        super().__init__(store, todos=todos, calendar=calendar)
