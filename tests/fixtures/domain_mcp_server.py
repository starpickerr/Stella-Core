"""Test-only upstreams; production MCP/SQLite/download code runs unchanged."""

import argparse
import importlib
import importlib.util
import io
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--domain", required=True)
args, rest = parser.parse_known_args()
root = Path(__file__).resolve().parents[3]
repo = (
    root / "MCP" / ("elearning_crawler" if args.domain == "elearning" else "email_mcp")
)
pkg = "elearning_mcp" if args.domain == "elearning" else "email_mcp"
sys.path.insert(0, str(repo))
module = importlib.import_module(pkg + ".server")
if args.domain == "elearning":

    class Canvas:
        base = "https://canvas.example.test"

        def __init__(self, service):
            self.service = service

        def get(self, *args, **kwargs):
            return {"id": 99}, None

        def list(self, path, params=None):
            if path.endswith("/courses"):
                return [{"id": 42, "name": "课程"}]
            if path.endswith("/files"):
                return [
                    {
                        "id": 4,
                        "filename": "讲义.pdf",
                        "url": self.base + "/files/4/download",
                        "size": 9,
                    }
                ]
            return []

        def open(self, *args, **kwargs):
            (self.service.store.root / "download-started").touch()
            if (self.service.store.root / "slow-download").exists():
                while not self.service.cancel_event.is_set():
                    time.sleep(0.01)
            return io.BytesIO(b"coursepdf")

    module.ElearningService._client = lambda self, cfg: Canvas(self)
else:
    spec = importlib.util.spec_from_file_location(
        "mail_test_fakes", repo / "tests/test_compatibility.py"
    )
    fakes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fakes)
    original = module.EmailService

    class Email(original):
        def __init__(self, *args, **kwargs):
            super().__init__(
                *args,
                **kwargs,
                opener=lambda: fakes.FakeImap({1: fakes._raw("<one@test>", "邮件")}),
            )

    module.EmailService = Email
sys.argv = [sys.argv[0], *rest]
module.cli()
