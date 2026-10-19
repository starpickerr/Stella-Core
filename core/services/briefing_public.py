"""Host entry points to the sole Briefing domain owner."""


def default_service():
    from core.services.briefing_gateway import briefing_plugin_enabled
    if not briefing_plugin_enabled():
        raise RuntimeError('briefing domain requires the stella.briefing plugin (STELLA_BRIEFING_PLUGIN=1)')
    from core.services.briefing_facade import BriefingPluginFacade
    return BriefingPluginFacade()


def dispatch_outbox(limit=20):
    return default_service().store.dispatch_outbox(limit)
