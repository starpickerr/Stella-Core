"""Static preflight for Stella's project-scoped Codex development policy."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _toml_load(path):
    if sys.version_info >= (3, 11):
        import tomllib as toml
    else:
        import tomli as toml
    with path.open("rb") as stream:
        return toml.load(stream)


def main():
    failures = []
    root_guide = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    core_guide = (ROOT / ".agents/AGENTS.md").read_text(encoding="utf-8")
    for target in (".agents/AGENTS.md", ".agents/rules/git.md",
                   ".agents/rules/skill-coordination.md", "develop", "main",
                   "Codex", "Cursor"):
        if target not in root_guide:
            failures.append(f"AGENTS.md missing {target}")
    for path in (ROOT / ".agents/skills").glob("*/AGENTS.md"):
        failures.append(f"skill guide must not be named AGENTS.md: {path.relative_to(ROOT)}")
    cursor_rules = list((ROOT / ".cursor/rules").glob("*.mdc"))
    always = [path.read_text(encoding="utf-8") for path in cursor_rules if "alwaysApply: true" in path.read_text(encoding="utf-8")]
    if not always:
        failures.append("missing always-on Cursor development rule")
    else:
        cursor_guide = "\n".join(always)
        for target in ("AGENTS.md", "develop", "scripts/quality_check.py incremental"):
            if target not in cursor_guide:
                failures.append(f"Cursor rule missing {target}")
    for name in ("architecture", "testing", "security", "git", "ui-design", "skill-coordination"):
        path = ROOT / ".agents/rules" / f"{name}.md"
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing rule {name}")
    if "scripts/quality_check.py incremental" not in core_guide:
        failures.append("core guide missing incremental gate")
    config = _toml_load(ROOT / ".codex/config.toml")
    if config.get("project_doc_max_bytes", 0) < 4096:
        failures.append("project instruction byte limit too small")
    sources = json.loads((ROOT / ".agents/skills/sources.json").read_text(encoding="utf-8"))
    documented = {row["skill"] for row in sources}
    installed = set()
    for skill_file in (ROOT / ".agents/skills").glob("*/SKILL.md"):
        name = skill_file.parent.name
        installed.add(name)
        header = skill_file.read_text(encoding="utf-8").split("---", 2)
        if len(header) < 3 or f"name: {name}" not in header[1] or "description:" not in header[1]:
            failures.append(f"invalid skill metadata {name}")
    if installed != documented:
        failures.append(f"skill inventory mismatch: installed={sorted(installed)} documented={sorted(documented)}")
    if not (ROOT / "docs/plans/active").is_dir():
        failures.append("missing active plan directory")
    for failure in failures:
        print(f"FAIL policy: {failure}")
    if not failures:
        print(f"PASS policy: root/core guides, TOML, six rule files, {len(installed)} project skills and plan directory")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
