"""Run reproducible, offline Stella Agent behavior scenarios."""

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from quality_check import isolated_env  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "evals/reports/latest.json")
    args = parser.parse_args()
    cases = json.loads((ROOT / "evals/datasets/agent_cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="stella-agent-eval-") as directory:
            command = [sys.executable, "-m", "pytest", case["test"], "-q"]
            try:
                result = subprocess.run(command, cwd=ROOT, env=isolated_env(Path(directory)),
                                        capture_output=True, text=True, timeout=120)
                passed = result.returncode == 0
                evidence = (result.stdout + result.stderr).strip().splitlines()[-12:]
            except (OSError, subprocess.TimeoutExpired) as error:
                passed = False
                evidence = [str(error)]
        results.append({"id": case["id"], "area": case["area"], "test": case["test"],
                        "grader": "pytest exit code is zero", "passed": passed, "evidence": evidence})
        print(f"{'PASS' if passed else 'FAIL'} eval {case['id']}", flush=True)
    report = {"kind": "deterministic scripted/mock Agent eval", "model_calls": "none",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "passed": sum(row["passed"] for row in results), "total": len(results), "results": results,
              "limitations": ["This suite does not measure live-model prompt-injection resistance or task completion rate.",
                              "Live provider evals require an explicit cost and credential plan."]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"REPORT {args.report}")
    return int(report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())
