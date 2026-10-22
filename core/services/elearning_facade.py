"""Facade over the stella.elearning MCP for desktop settings, tools and briefing.

Exposes the contract surface plus drop-in names for the legacy
the public settings API. Policy audit events queued by
the MCP worker (it cannot reach the host audit log) are recorded here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from core.services import elearning_gateway

from common.log import logger

_RECORDING = {"save_settings", "save_file_sync_settings", "sync_files", "delete_settings"}


def _paths() -> tuple[Path, Path]:
    from common.state_dir import briefing_db

    briefing = briefing_db(ensure=False)
    return briefing.parent.parent / "elearning", briefing.parent


def _unwrap(result: dict[str, Any]) -> Any:
    status = result.get("status")
    if status == "failed":
        err = result.get("error") or {}
        message = err.get("message") or "elearning MCP call failed"
        if err.get('code') == 'cancelled':
            from agent.protocol.cancel import AgentCancelledError
            raise AgentCancelledError(message)
        if err.get("code") == "not_found":
            raise KeyError(message)
        raise ValueError(message)
    if status != "succeeded":
        raise RuntimeError(f"elearning MCP returned {status}")
    return result.get("value")


class ElearningMcpFacade:
    """Drop-in for Application._Port over the managed elearning MCP connection."""

    def __init__(self, *, purpose: str | None = None):
        self._purpose = purpose

    def __getattr__(self, name: str):
        names = elearning_gateway.ELEARNING_METHOD_PARAMS.get(name)
        if names is None or name == "drain_audit_events":
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            if len(args) > len(names):
                raise TypeError(f"{name}() takes at most {len(names)} arguments")
            params = dict(zip(names, args))
            for key, value in kwargs.items():
                if key not in names:
                    raise TypeError(f"{name}() got an unexpected keyword argument {key!r}")
                if key in params:
                    raise TypeError(f"{name}() got multiple values for argument {key!r}")
                params[key] = value
            return self._value(name, params)

        call.__name__ = name
        return call

    def _invoke(self, method: str, params: dict[str, Any], purpose: str | None = None) -> Any:
        return _unwrap(elearning_gateway.invoke_elearning(method, params, purpose=purpose or self._purpose))

    def _value(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return self._invoke(method, params)
        finally:
            if method in _RECORDING:
                self._record_audit()

    def _record_audit(self) -> None:
        """Move MCP-queued audit events into the host permission audit log."""
        try:
            events = self._invoke("drain_audit_events", {}, purpose="interactive")
            if not events:
                return
            from agent.permission.audit import record

            for event in events:
                event.pop("ts", None)
                record(**event)
        except Exception as exc:  # audit pickup is retried on the next write
            logger.warning("[eLearning] audit drain deferred: %s", exc)

    # ---- public settings aliases ---------------
    def public_settings(self) -> dict:
        return self.get_settings()

    def check_connection(self, payload: dict) -> list:
        return self.test_connection(payload)


class ElearningMcpSource:
    """Briefing ``Source`` backed by the MCP; credentials never leave it."""

    name = "elearning"

    def __init__(self, *, account_id: str, username: str = "", purpose: str = "background",
                 facade: ElearningMcpFacade | None = None):
        self.account_id = account_id
        self.cancel_event = None
        self.display_name = "eLearning · " + username
        self._facade = facade or ElearningMcpFacade(purpose=purpose)

    def fetch(self, cursors: Dict[str, str]):
        from core.services.source_types import FetchedItem, FetchResult

        cursors = dict(cursors)
        window = {key: cursors.pop(key) for key in ("since", "until") if key in cursors}
        from core.plugins.cancellation import cancellation_scope
        from core.plugins.caller import consumer_plugin_scope
        from core.data.runtime import current_service
        from core.data.store import stable_id
        from core.data.usage import UsageService
        def check_usage():
            service = current_service()
            source_id = 'mcp:elearning:' + stable_id(self.account_id)
            try:
                source = service.store.source(source_id)
            except KeyError:
                return  # Compatibility for owners not yet discovered in Data.
            binding = UsageService(service).binding('stella.briefing', source_id)
            if not source['enabled'] or not source['present'] or not binding['selected'] or not binding['enabled']:
                raise PermissionError('Data source usage is disabled for this consumer')
            return source['revision'], binding['revision']
        with consumer_plugin_scope('stella.briefing'), cancellation_scope(self.cancel_event):
            revision = check_usage()
            result = self._facade.fetch_source(cursors=cursors, **window)
            if check_usage() != revision:
                raise PermissionError('Data source or usage changed during fetch')
            if result.get('account_id') != self.account_id:
                raise PermissionError('eLearning account changed during fetch')
        return FetchResult(items=[FetchedItem(**row) for row in result["items"]],
                           cursors=result["cursors"], errors=result["errors"])


def elearning_sources(purpose: str = "background") -> list[ElearningMcpSource]:
    facade = ElearningMcpFacade(purpose=purpose)
    settings = ElearningMcpFacade(purpose="interactive").get_settings()
    from core.data.store import stable_id
    from core.data.runtime import current_service
    from core.data.usage import UsageService
    service = current_service()
    service.discover(provider_ids={'elearning'})
    source_id = 'mcp:elearning:' + stable_id(settings['account_id'])
    try:
        source = service.store.source(source_id)
    except KeyError:
        enabled = settings['enabled']  # Preserve legacy accounts before first Data discovery.
    else:
        enabled = source['enabled'] and source['present'] and UsageService(service).enabled('stella.briefing', source_id)
    if not enabled:
        return []
    return [ElearningMcpSource(account_id=settings["account_id"], username=settings["username"],
                                  purpose=purpose, facade=facade)]
