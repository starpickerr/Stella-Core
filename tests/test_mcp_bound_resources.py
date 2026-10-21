"""MCP state is bound at trusted startup, never selected by tool arguments."""

import json
import pytest
from tests.test_managed_mcp_domains import server_config
from agent.tools.mcp.mcp_client import McpClient


@pytest.mark.parametrize(
    "domain,method", [("email", "list_accounts"), ("elearning", "get_settings")]
)
def test_tool_cannot_replace_bound_state_or_identity(tmp_path, domain, method):
    client = McpClient(server_config(domain, tmp_path / "alice"))
    try:
        assert client.initialize()
        for forged in [
            {"data_dir": str(tmp_path / "bob")},
            {"_hostDataHandle": {"dataDir": str(tmp_path / "bob")}},
            {"user_id": "bob"},
        ]:
            result = client._send_request(
                "tools/call", {"name": method, "arguments": forged}
            )
            assert result["result"]["isError"]
        assert not (tmp_path / "bob").exists()
    finally:
        client.shutdown()


def test_other_users_mailbox_id_is_not_visible_to_the_bound_server(tmp_path):
    alice, bob = [
        McpClient(server_config("email", tmp_path / user)) for user in ["alice", "bob"]
    ]
    try:
        assert alice.initialize() and bob.initialize()
        account = json.loads(
            alice.call_tool(
                "save_account",
                {
                    "payload": {
                        "host": "imap.example.test",
                        "user": "alice@example.test",
                        "password": "test-secret",
                    }
                },
            )
        )["value"]
        result = bob._send_request(
            "tools/call",
            {"name": "get_account", "arguments": {"account_id": account["id"]}},
        )
        assert result["result"]["isError"]
        assert "test-secret" not in json.dumps(result)
    finally:
        alice.shutdown()
        bob.shutdown()
