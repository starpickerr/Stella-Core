"""A linked Skill workflow must exist before project policy can pass."""

from scripts import check_dev_policy


def test_absent_development_spec_skips_policy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_dev_policy, "ROOT", tmp_path)

    assert check_dev_policy.main() == 0
    assert "SKIP policy" in capsys.readouterr().out


def test_missing_skill_coordination_rule_fails_policy(tmp_path, monkeypatch, capsys):
    (tmp_path / "AGENTS.md").write_text(
        "Codex Cursor .agents/AGENTS.md .agents/rules/git.md .agents/rules/skill-coordination.md develop main",
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
    for relative in (
        ".agents/tasks/active", ".agents/tasks/completed",
        ".agents/audits/code-review", ".agents/audits/security", ".agents/audits/product",
        ".agents/runs", "evals/datasets", ".agents/workflows",
    ):
        (tmp_path / relative).mkdir(parents=True)
    for relative in (
        ".agents/workflows/development.md",
        ".agents/workflows/skill-management.md",
        ".agents/workflows/development-evaluation.md",
        "evals/README.md", "evals/run.py",
    ):
        (tmp_path / relative).write_text("present\n", encoding="utf-8")
    monkeypatch.setattr(check_dev_policy, "ROOT", tmp_path)

    assert check_dev_policy.main() == 1
    assert "missing rule skill-coordination" in capsys.readouterr().out

    (rules / "skill-coordination.md").write_text("workflow\n", encoding="utf-8")
    cursor_rule = tmp_path / ".cursor/rules/stella-development.mdc"
    cursor_rule.parent.mkdir(parents=True)
    cursor_rule.write_text("alwaysApply: true\nAGENTS.md .agents/ develop scripts/quality_check.py incremental\n", encoding="utf-8")
    assert check_dev_policy.main() == 0

    skill_guide = tmp_path / ".agents/skills/example/AGENTS.md"
    skill_guide.parent.mkdir()
    skill_guide.write_text("guide\n", encoding="utf-8")
    assert check_dev_policy.main() == 1
    assert "skill guide must not be named AGENTS.md" in capsys.readouterr().out
