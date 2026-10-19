from __future__ import annotations

import pytest

from core.plugins.bridge import BridgeRegistry


def test_bridge_binds_identity_and_rejects_mismatch():
    bridges = BridgeRegistry()
    ch = bridges.open(
        plugin_id="stella.sample.alpha",
        user_id="u1",
        instance_id="i1",
        generation=1,
        page_id="main",
    )
    assert bridges.authorize_invoke(
        ch.channel_nonce,
        plugin_id="stella.sample.alpha",
        generation=1,
        page_id="main",
    ).user_id == "u1"
    with pytest.raises(PermissionError):
        bridges.authorize_invoke(
            ch.channel_nonce,
            plugin_id="stella.sample.alpha",
            generation=2,
            page_id="main",
        )


def test_revoke_generation_closes_channels():
    bridges = BridgeRegistry()
    ch = bridges.open(
        plugin_id="stella.sample.alpha",
        user_id="u1",
        instance_id="i1",
        generation=3,
        page_id="settings",
    )
    bridges.revoke_generation("stella.sample.alpha", 3)
    with pytest.raises(PermissionError):
        bridges.resolve(ch.channel_nonce)
