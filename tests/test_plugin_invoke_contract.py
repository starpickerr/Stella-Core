"""RPC must match Plugin API 1.0 InvokeParams / HostContext / OperationResult."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.plugins.contract import (
    ContractError,
    build_host_context,
    build_invoke_params,
    validate_host_context,
    validate_invoke_params,
    validate_operation_result,
)
from core.plugins.host import PluginSession
from core.plugins.runtime_hub import DEFAULT_REGISTRY


def test_invoke_params_require_contract_input_deadline_context():
    with pytest.raises(ContractError):
        validate_invoke_params({"method": "ping", "params": {}})


def test_build_and_validate_roundtrip():
    ctx = build_host_context(
        user_id="u1",
        instance_id="i1",
        generation=1,
        origin="ui",
        grant_ref="g1",
    )
    validate_host_context(ctx)
    params = build_invoke_params(
        contract="stella.sample.alpha@1",
        method="ping",
        input_payload={"echo": 1},
        context=ctx,
        deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    validate_invoke_params(params)


def test_session_invoke_uses_contract_shape(tmp_path):
    from core.plugins.authz import DEFAULT_AUTHZ

    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=DEFAULT_REGISTRY,
        user_id="u-test",
    )
    DEFAULT_AUTHZ.issue(
        grant_ref="test-grant",
        plugin_id="stella.sample.alpha",
        user_id="u-test",
        capabilities=["sample.ping", "plugin.invoke"],
        purposes=["interactive"],
    )
    try:
        session.start()
        result = session.invoke_contract(
            contract="stella.sample.alpha@1",
            method="ping",
            input_payload={"echo": "x"},
            origin="ui",
            grant_ref="test-grant",
            permissions=("sample.ping",),
        )
        validate_operation_result(result)
        assert result["status"] == "succeeded"
        assert result["value"]["plugin"] == "alpha"
    finally:
        session.dispose()


def test_read_only_grant_can_query_but_cannot_write(tmp_path):
    from core.plugins.authz import PluginAuthorizationStore
    from core.plugins.registry import PluginRegistry

    authz = PluginAuthorizationStore()
    session = PluginSession(Path("stella-plugins-workspace/plugins/bills"),
                            source_label="test", registry=PluginRegistry(), authz=authz)
    authz.issue(grant_ref="read", plugin_id="stella.bills", user_id=session.user_id,
                capabilities=["bills.read"], purposes=["interactive"])
    try:
        session.start()
        args = dict(contract="stella.bills@1", origin="ui", grant_ref="read",
                    data_handle={"dbPath": str(tmp_path / "bills.db"), "namespace": "stella.bills"})
        result = session.invoke_contract(method="list_ledger", input_payload={"year": 2026, "month": 10}, **args)
        assert result["status"] == "succeeded"
        with pytest.raises(PermissionError, match="bills.write"):
            session.invoke_contract(method="create_ledger", input_payload={}, **args)
        with pytest.raises((PermissionError, ValueError), match="unknown|not declared"):
            session.invoke_contract(method="undeclared", input_payload={}, **args)
    finally:
        session.dispose()
