"""Run a development check with disposable Stella state and no provider secrets."""

import subprocess
import sys
import tempfile
from pathlib import Path

from quality_check import isolated_env


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_isolated.py COMMAND [ARGS...]")
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="stella-check-") as directory:
        return subprocess.call(sys.argv[1:], cwd=root, env=isolated_env(Path(directory)))


if __name__ == "__main__":
    raise SystemExit(main())
