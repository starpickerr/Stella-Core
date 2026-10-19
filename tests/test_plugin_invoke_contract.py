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
