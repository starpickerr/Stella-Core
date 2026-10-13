"""Exercise briefing resources declared for the frozen desktop backend."""

import ast
from pathlib import Path
import shutil

from agent.briefing import actions, store
from agent.briefing.service import BriefingService


def test_packaged_briefing_detail_initializes_actions(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = ast.parse((root / "desktop/build/stella-backend.spec").read_text())
    datas = next(node.value for node in spec.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "datas"
                         for target in node.targets))
    package = tmp_path / "_internal/agent/briefing"
    package.mkdir(parents=True)
    for entry in datas.elts:
        source, destination = entry.elts
        if ast.literal_eval(destination) == "agent/briefing":
            path = root.joinpath(*(ast.literal_eval(arg) for arg in source.args))
            shutil.copyfile(path, package / path.name)

    monkeypatch.setattr(store, "_SCHEMA_PATH", package / "schema.sql")
    monkeypatch.setattr(actions, "__file__", str(package / "actions.py"))
    service = BriefingService(store.BriefingStore(tmp_path / "briefing.db"))
    briefing = service.start_briefing(briefing_date="2026-10-13")
    detail = service.get_briefing(briefing.id)

    assert detail["briefing"].id == "brf-2026-10-13"
    assert detail["actions"] == {}
    assert isinstance(detail["preferences"], dict)
