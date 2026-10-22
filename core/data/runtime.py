"""Trusted provider registrations and adapters for consumers of Data Service."""

from common.state_dir import data_service_db
from core.data.providers import McpProvider, EMAIL_MAPPING, DataSource
from core.data.service import DataService, ProviderRegistry
from core.data.owned_providers import PluginResourceProvider, OWNERS
from core.data.elearning_provider import ElearningProvider


def current_service():
    providers = ProviderRegistry()
    providers.register("email", McpProvider("email", EMAIL_MAPPING))
    providers.register('elearning', ElearningProvider())
    for owner in OWNERS:
        providers.register(owner, PluginResourceProvider(owner))
    return DataService(data_service_db(), providers)


def consumer_sources(*, provider_ids=None, consumer_id=None):
    service = current_service()
    service.discover()
    sources = []
    for source in service.list_sources():
        if (
            not source["enabled"]
            or not source["present"]
            or provider_ids is not None
            and source["provider"] not in provider_ids
        ):
            continue
        if consumer_id:
            from core.data.usage import UsageService
            if not UsageService(service).enabled(consumer_id, source['id']):
                continue
        provider = service.providers.get(source["provider"])
        available = getattr(provider, "available", lambda: True)
        if available() and callable(getattr(provider, "fetch", None)):
            sources.append(DataSource(service, source, consumer_id=consumer_id))
    return sources
