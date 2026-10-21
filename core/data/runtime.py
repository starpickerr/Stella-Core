"""Trusted provider registrations and adapters for consumers of Data Service."""

from common.state_dir import data_service_db
from core.data.providers import McpProvider, EMAIL_MAPPING, DataSource
from core.data.service import DataService, ProviderRegistry
from core.data.workspace_provider import WorkspaceProvider


def current_service():
    providers = ProviderRegistry()
    providers.register("email", McpProvider("email", EMAIL_MAPPING))
    providers.register("workspace", WorkspaceProvider())
    return DataService(data_service_db(), providers)


def consumer_sources(*, provider_ids=None):
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
        provider = service.providers.get(source["provider"])
        available = getattr(provider, "available", lambda: True)
        if available() and callable(getattr(provider, "fetch", None)):
            sources.append(DataSource(service, source))
    return sources
