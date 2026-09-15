from eval_harness.config import GateConfig
from eval_harness.gate import check_gate
from eval_harness.report import CaseResult, RunInfo, RunReport, Status, group, summarise


def result(case_id: str, category: str, status: Status, severity: str = "high") -> CaseResult:
    return CaseResult(
        id=case_id,
        category=category,
        severity=severity,
        grading="deterministic",
        status=status,
        input="",
    )


def report(
    results: list[CaseResult], judge: str | None = None, prompt_sha: str | None = None
) -> RunReport:
    return RunReport(
        run=RunInfo(
            id="run",
            started_at="",
            finished_at="",
            target="t",
            judge_model=judge,
            judge_prompt_sha=prompt_sha,
            harness_version="0",
        ),
        summary=summarise(results),
        suites=group(results, "category"),
        severities=group(results, "severity"),
        cases=results,
    )


def suite(
    category: str, passed: int, failed: int, critical_failures: tuple[str, ...] = ()
) -> list[CaseResult]:
    cases = [result(f"{category}-p{i}", category, "passed") for i in range(passed)]
    cases += [result(f"{category}-f{i}", category, "failed") for i in range(failed)]
    cases += [result(cid, category, "failed", severity="critical") for cid in critical_failures]
    return cases


def test_without_a_baseline_only_critical_failures_fail():
    assert check_gate(report(suite("docs", 3, 2)), None, GateConfig()).passed
    gate = check_gate(report(suite("docs", 3, 0, ("C-1",))), None, GateConfig())
    assert gate.problems == ["critical failures: C-1"]


def test_a_drop_beyond_the_tolerance_fails_and_a_small_one_does_not():
    baseline = report(suite("docs", 50, 0))

    small = check_gate(report(suite("docs", 49, 1)), baseline, GateConfig(tolerance=0.02))
    large = check_gate(report(suite("docs", 45, 5)), baseline, GateConfig(tolerance=0.02))

    assert small.passed
    assert large.problems == ["docs: pass rate 90.0%, baseline 100.0% (down 10.0%, tolerance 2.0%)"]


def test_a_known_critical_failure_passes_and_a_new_one_fails():
    baseline = report(suite("safety", 3, 0, ("C-1",)))

    assert check_gate(
        report(suite("safety", 3, 0, ("C-1",))), baseline, GateConfig(tolerance=1)
    ).passed
    gate = check_gate(
        report(suite("safety", 3, 0, ("C-1", "C-2"))), baseline, GateConfig(tolerance=1)
    )
    assert gate.problems == ["safety: new critical failures C-2"]


def test_errors_count_as_failures():
    run = report([result("A", "docs", "error", severity="critical"), result("B", "docs", "passed")])

    assert run.summary.pass_rate == 0.5
    assert not check_gate(run, None, GateConfig()).passed


def test_runs_graded_differently_cannot_be_compared():
    with_judge = report(suite("docs", 1, 0), judge="anthropic:claude-sonnet-5", prompt_sha="abc")
    without = report(suite("docs", 1, 0))

    assert not check_gate(with_judge, without, GateConfig()).passed
    changed = check_gate(
        with_judge,
        report(suite("docs", 1, 0), judge="openai:gpt-5", prompt_sha="abc"),
        GateConfig(),
    )
    assert changed.passed and "recalibrate" in changed.notes[0]


def test_notes_new_categories_and_fixed_critical_cases():
    baseline = report(suite("docs", 2, 0, ("C-1",)))
    current = report(suite("docs", 3, 0) + suite("tools", 1, 0))

    gate = check_gate(current, baseline, GateConfig())

    assert gate.passed
    assert "tools: new category, no baseline pass rate" in gate.notes
    assert "critical cases fixed since the baseline: C-1" in gate.notes


def test_minimum_pass_rate_applies_whatever_the_baseline():
    gate = check_gate(report(suite("docs", 1, 1)), None, GateConfig(min_pass_rate=0.8))
    assert gate.problems == ["overall pass rate 50.0% is below the minimum 80.0%"]
