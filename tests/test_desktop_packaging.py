"""Briefing resources belong to the independent package, not the Core backend."""
import ast
from pathlib import Path
import shutil


def test_packaged_briefing_detail_initializes_actions(tmp_path, monkeypatch, briefing_plugin_env):
    from core.services.briefing_facade import BriefingPluginFacade
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'desktop/build/stella-backend.spec').read_text())
    datas = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'datas' for target in node.targets))
    assert all(ast.literal_eval(entry.elts[1]) != 'agent/briefing' for entry in datas.elts)
    package = tmp_path / 'plugin'
    shutil.copytree(root / 'stella-plugins-workspace/plugins/briefing', package)
    monkeypatch.setenv('STELLA_BRIEFING_PLUGIN_ROOT', str(package))
    monkeypatch.setattr('core.services.briefing_facade._db_path', lambda: tmp_path / 'briefing.db')
    service = BriefingPluginFacade()
    briefing = service.start_briefing(briefing_date='2026-10-13')
    detail = service.get_briefing(briefing.id)
    assert detail['briefing'].id == 'brf-2026-10-13'
    assert detail['actions'] == {}
    assert isinstance(detail['preferences'], dict)
