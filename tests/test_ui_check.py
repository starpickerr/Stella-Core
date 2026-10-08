"""Browser check lifecycle cannot reuse another running application."""
import socket
import sys
import pytest
from scripts.ui_check import run_server


def test_occupied_port_is_rejected():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with pytest.raises(RuntimeError, match='occupied'):
            run_server([sys.executable, '-c', 'pass'], [sys.executable, '-c', 'pass'], port=listener.getsockname()[1])


def test_failed_server_cannot_pass_client():
    with pytest.raises(RuntimeError, match='exited'):
        run_server([sys.executable, '-c', 'raise SystemExit(9)'], [sys.executable, '-c', 'pass'])
