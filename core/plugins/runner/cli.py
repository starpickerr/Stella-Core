"""Dedicated stella-plugin-runner CLI entry (packaged separately from app.py)."""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    # Must not import application/app, PluginManager, scheduler, or RunRecord recovery.
    forbidden = ("app", "application.api", "plugins.plugin_manager", "agent.scheduler")
    for name in forbidden:
        if name in sys.modules:
            raise SystemExit(f"stella-plugin-runner refuses polluted process: {name} already imported")
    os.environ.setdefault("STELLA_PLUGIN_WORKER", "1")
    from core.plugins.runner.__main__ import main as runner_main

    return runner_main()


if __name__ == "__main__":
    raise SystemExit(main())
