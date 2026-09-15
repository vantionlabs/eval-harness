"""The `evals` command end to end, on the example support assistant."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from eval_harness.cli import main
from tests.conftest import EXAMPLE


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A copy of the example, so reports and baselines are written somewhere disposable."""
    target = tmp_path / "support_assistant"
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns("reports", "__pycache__"))
    # Each test loads the adapter from its own copy, not one imported by an earlier test.
    for module in ("eval_adapter", "assistant"):
        sys.modules.pop(module, None)
    return target


def run(project: Path, *args: str) -> int:
    return main(["-c", str(project / "evals.yaml"), *args])


def test_validate_counts_the_cases(project: Path, capsys: pytest.CaptureFixture[str]):
    assert run(project, "validate") == 0
    assert "17 cases in 2 test set(s)" in capsys.readouterr().out


def test_run_passes_against_the_committed_baseline_and_writes_reports(project: Path, capsys):
    assert run(project, "run", "--no-judge") == 0

    out = capsys.readouterr().out
    assert "## ✅ No regressions" in out
    latest = json.loads((project / "reports" / "latest.json").read_text())
    assert latest["summary"]["failed_critical"] == []
    assert any(p.suffix == ".md" for p in (project / "reports").iterdir())


def test_run_fails_when_a_category_regresses(project: Path, capsys):
    # Pretend the baseline got the escalation case right: this run now looks like a regression.
    baseline_path = project / "baseline.json"
    baseline = json.loads(baseline_path.read_text())
    baseline["suites"]["escalation"]["pass_rate"] = 1.0
    baseline_path.write_text(json.dumps(baseline))

    assert run(project, "run", "--no-judge") == 1
    assert "escalation: pass rate 0.0%, baseline 100.0%" in capsys.readouterr().out


def test_a_new_critical_failure_fails_the_gate(project: Path, capsys):
    (project / "kb" / "billing" / "refund-policy.md").write_text(
        "# Refund policy\n\nYou can get a full refund at any time, no questions asked.\n"
    )

    assert run(project, "run", "--no-judge") == 1
    assert "new critical failures EVS-002" in capsys.readouterr().out


def test_a_filtered_run_is_not_compared_with_the_baseline(project: Path, capsys):
    assert run(project, "run", "--no-judge", "--case", "EVS-007") == 0
    assert "filtered run: not compared with the baseline" in capsys.readouterr().out


def test_a_broken_test_set_exits_with_2(project: Path, capsys):
    (project / "test-set.csv").write_text("id,category,input,severity\nX,c,hi,urgent\n")

    assert run(project, "validate") == 2
    assert "severity must be one of" in capsys.readouterr().err
