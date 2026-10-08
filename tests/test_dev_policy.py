"""A linked Skill workflow must exist before project policy can pass."""

from scripts import check_dev_policy


def test_missing_skill_coordination_rule_fails_policy(tmp_path, monkeypatch, capsys):
    (tmp_path / "AGENTS.md").write_text(
        ".agents/AGENTS.md .agents/rules/git.md .agents/rules/skill-coordination.md develop main",
        encoding="utf-8",
    )
    core = tmp_path / ".agents/AGENTS.md"
    core.parent.mkdir()
    core.write_text("scripts/quality_check.py incremental", encoding="utf-8")
    rules = tmp_path / ".agents/rules"
    rules.mkdir()
    for name in ("architecture", "testing", "security", "git", "ui-design"):
        (rules / f"{name}.md").write_text("rule\n", encoding="utf-8")
    (tmp_path / ".agents/skills/sources.json").parent.mkdir()
    (tmp_path / ".agents/skills/sources.json").write_text("[]", encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex/config.toml").write_text("project_doc_max_bytes = 32768\n", encoding="utf-8")
    (tmp_path / "docs/plans/active").mkdir(parents=True)
    monkeypatch.setattr(check_dev_policy, "ROOT", tmp_path)

    assert check_dev_policy.main() == 1
    assert "missing rule skill-coordination" in capsys.readouterr().out

    (rules / "skill-coordination.md").write_text("workflow\n", encoding="utf-8")
    assert check_dev_policy.main() == 0
