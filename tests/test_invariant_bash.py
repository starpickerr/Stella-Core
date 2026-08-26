import pytest
from agent.tools.bash.bash import Bash


@pytest.mark.parametrize("command", [
    "cat ~/.stella/.env",
    "cat .stella/.env",
    "less ~/.stella/.env",
    "cat /home/user/.stella/.env",
])
def test_credential_file_access_is_blocked(command):
    result = Bash().execute({"command": command})
    assert result.status == "error", f"Expected blocked result for: {command}"
    assert "Access denied" in str(result.result)


@pytest.mark.parametrize("command", [
    "ls ~/.stella/skills",
    "ls ~/.stella/",
    "echo hello",
])
def test_legitimate_stella_directory_access_is_not_blocked(command):
    result = Bash().execute({"command": command})
    assert "Access denied" not in str(result.result)
