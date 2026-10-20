"""Trusted source ownership for Core adapters; never supplied by tool arguments."""

_PLUGIN_TOOLS = {
    'bills': ('stella.bills',),
    'briefing': ('stella.briefing',),
    'calendar': ('stella.calendar',),
    'todos': ('stella.tasks',),
    'elearning': ('stella.elearning',),
    'agent_hub': ('stella.agent-hub',),
    'scheduler': ('stella.automation',),
    'memory': ('stella.memory',),
    'memory_search': ('stella.memory',),
    'memory_get': ('stella.memory',),
    'memory_write': ('stella.memory',),
    'knowledge': ('stella.knowledge',),
    'knowledge_search': ('stella.knowledge',),
    'knowledge_get': ('stella.knowledge',),
    'knowledge_write': ('stella.knowledge',),
    'apple': ('stella.calendar', 'stella.tasks'),
}


def _owners(name, tool=None):
    if name == 'scheduler' and tool is not None and getattr(tool, 'task_store', None) is not None:
        from core.services.automation_facade import plugin_serves
        if not plugin_serves(tool.task_store):
            return ()  # The supported legacy JSON scheduler is served entirely by Core.
    return _PLUGIN_TOOLS.get(name, ())


def tool_source(name, tool=None):
    plugins = _owners(name, tool)
    return {'type': 'plugin' if plugins else 'builtin', 'plugin_ids': list(plugins)}


def plugin_tool_available(name, params=None, *, tool=None):
    """Apply managed intent without starting workers or reviving legacy routes.

    Apple has two independently managed providers: offer the tool when either
    is usable, then check the selected provider at execution. Actual gateways
    still own admission for calls racing a lifecycle transition.
    """
    plugins = _owners(name, tool)
    if name == 'apple' and isinstance(params, dict):
        kind = params.get('kind')
        if kind in ('calendar', 'reminders'):
            plugins = ('stella.calendar' if kind == 'calendar' else 'stella.tasks',)
    if not plugins:
        return True
    from core.plugins.caller import managed_data_lease
    for plugin in plugins:
        try:
            with managed_data_lease(plugin):
                return True
        except PermissionError:
            continue
        except Exception:
            return False
    return False
