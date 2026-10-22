"""Core collection must skip sibling MCP packages that are not in the checkout."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.mcp_checkout import require_checkout

ROOT = Path(__file__).resolve().parents[1]


def test_missing_checkout_skips_instead_of_raising(tmp_path):
    missing = tmp_path / 'email_mcp' / '__init__.py'
    with pytest.raises(pytest.skip.Exception) as caught:
        require_checkout(missing, 'Email MCP package is not in this checkout')
    assert caught.value.allow_module_level is True
    assert 'Email MCP package is not in this checkout' in str(caught.value)


def test_missing_checkout_skips_collection(tmp_path):
    module = tmp_path / 'test_missing_mcp.py'
    module.write_text(
        "from pathlib import Path\n"
        "from tests.mcp_checkout import require_checkout\n"
        "require_checkout(Path('missing-mcp-package.py'), 'Email MCP package is not in this checkout')\n"
        "\n"
        "def test_should_not_run():\n"
        "    raise AssertionError('collected')\n",
        encoding='utf-8',
    )
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', str(module), '-q'],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(ROOT)},
    )
    assert result.returncode in {0, 5}, result.stdout + result.stderr
    assert '1 skipped' in result.stdout
    assert 'ERROR' not in result.stdout


def test_present_checkout_returns_the_file(tmp_path):
    present = tmp_path / 'email_mcp' / '__init__.py'
    present.parent.mkdir()
    present.write_text('', encoding='utf-8')
    assert require_checkout(present, 'unused') == present
