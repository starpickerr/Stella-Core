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
