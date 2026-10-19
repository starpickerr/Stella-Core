from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


def test_revoked_grant_blocks_invoke():
    authz = PluginAuthorizationStore()
    registry = PluginRegistry()
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="sample",
        registry=registry,
        user_id="u1",
        authz=authz,
    )
    authz.issue(
        grant_ref="g1",
        plugin_id="stella.sample.alpha",
        user_id="u1",
        capabilities=["sample.ping"],
    )
    try:
        session.start()
        authz.revoke("g1")
        with pytest.raises(PermissionError, match="revoked"):
            session.invoke_contract(
                contract="stella.sample.alpha@1",
                method="ping",
                input_payload={},
                origin="ui",
                grant_ref="g1",
                permissions=["sample.ping"],
            )
    finally:
        session.dispose()


def test_missing_capability_denied():
    authz = PluginAuthorizationStore()
    assert authz.get("missing") is None
    with pytest.raises(PermissionError, match="unknown grantRef"):
        authz.check(
            grant_ref="missing",
            plugin_id="stella.sample.alpha",
            user_id="u1",
            required_capabilities=["sample.ping"],
            purpose="interactive",
            generation=1,
            context_generation=1,
        )


@pytest.mark.parametrize("domain", ["bills", "todos", "calendar", "briefing", "automation", "email", "elearning"])
def test_gateway_worker_restart_does_not_restore_revoked_grant(domain, monkeypatch):
    import importlib

    gateway = importlib.import_module(f"core.services.{domain}_gateway")
    shutdown = getattr(gateway, f"shutdown_{domain}_session")
    ensure = getattr(gateway, f"ensure_{domain}_session")
    authz = PluginAuthorizationStore()
    shutdown()
    monkeypatch.setattr(gateway, "DEFAULT_AUTHZ", authz)
    monkeypatch.setattr("core.plugins.host.DEFAULT_AUTHZ", authz)
    monkeypatch.setattr(gateway, "DEFAULT_REGISTRY", PluginRegistry())
    try:
        ensure()
        grant_ref = gateway._GRANT_REF
        authz.revoke(grant_ref)
        shutdown()
        session = ensure()
        with pytest.raises(PermissionError, match="revoked"):
            session.authz.check(grant_ref=grant_ref, plugin_id=session.plugin_id,
                                user_id=session.user_id, required_capabilities=[],
                                purpose="interactive", generation=session.generation,
                                context_generation=session.generation)
    finally:
        shutdown()


@pytest.mark.parametrize("domain", ["email", "elearning"])
def test_stopped_gateway_applies_purpose_changes_without_restoring_revocation(domain, monkeypatch):
    import importlib

    gateway = importlib.import_module(f"core.services.{domain}_gateway")
    shutdown = getattr(gateway, f"shutdown_{domain}_session")
    ensure = getattr(gateway, f"ensure_{domain}_session")
    set_purposes = getattr(gateway, f"set_{domain}_purposes")
    shutdown()
    authz = PluginAuthorizationStore()
    monkeypatch.setattr(gateway, "DEFAULT_AUTHZ", authz)
    monkeypatch.setattr(gateway, "DEFAULT_REGISTRY", PluginRegistry())
    monkeypatch.setattr(gateway, "_PURPOSES", {"interactive", "read", "background"})
    try:
        ensure()
        shutdown()
        set_purposes({"interactive", "read"})
        session = ensure()
        grant = session.authz.get(gateway._GRANT_REF)
        assert grant.purposes == frozenset({"interactive", "read"})
        session.authz.revoke(gateway._GRANT_REF)
        set_purposes({"interactive"})
        assert session.authz.get(gateway._GRANT_REF).revoked is True
    finally:
        shutdown()
