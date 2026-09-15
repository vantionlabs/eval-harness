"""The regression gate: compare a run with a baseline and decide whether CI passes.

The gate fails when:

- a category's pass rate drops more than `tolerance` below the baseline,
- a critical case fails that did not fail in the baseline (with no baseline, any
  critical failure),
- the overall pass rate is below `min_pass_rate`,
- the run and the baseline were graded differently, so they cannot be compared.

A category's pass rate hides its size, so a drop in a small category is still a
drop. Review the failures list rather than raising the tolerance.
"""

from dataclasses import dataclass, field

from eval_harness.config import GateConfig
from eval_harness.report import RunReport


@dataclass(frozen=True)
class GateResult:
    passed: bool
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[str]:
        return [*self.problems, *self.notes]


def check_gate(current: RunReport, baseline: RunReport | None, config: GateConfig) -> GateResult:
    problems: list[str] = []
    notes: list[str] = []

    overall = current.summary.pass_rate
    if overall is None:
        problems.append("no case was graded")
    elif overall < config.min_pass_rate:
        problems.append(
            f"overall pass rate {overall:.1%} is below the minimum {config.min_pass_rate:.1%}"
        )

    if baseline is None:
        if current.summary.failed_critical:
            problems.append(f"critical failures: {', '.join(current.summary.failed_critical)}")
        notes.append("no baseline to compare with")
        return GateResult(passed=not problems, problems=problems, notes=notes)

    if bool(current.run.judge_model) != bool(baseline.run.judge_model):
        problems.append(
            "the run and the baseline were graded differently (one with a judge, one without); "
            "update the baseline"
        )
        return GateResult(passed=False, problems=problems, notes=notes)
    if current.run.judge_model != baseline.run.judge_model:
        notes.append(
            f"judge changed from {baseline.run.judge_model} to {current.run.judge_model}; "
            "recalibrate before trusting the comparison"
        )
    elif current.run.judge_prompt_sha != baseline.run.judge_prompt_sha:
        notes.append(
            "judge prompt changed since the baseline; recalibrate before trusting the comparison"
        )

    for name, suite in current.suites.items():
        base = baseline.suites.get(name)
        new_critical = sorted(
            set(suite.failed_critical) - set(base.failed_critical if base else [])
        )
        if new_critical:
            problems.append(f"{name}: new critical failures {', '.join(new_critical)}")
        if base is None:
            notes.append(f"{name}: new category, no baseline pass rate")
            continue
        if suite.pass_rate is None or base.pass_rate is None:
            continue
        drop = base.pass_rate - suite.pass_rate
        # Rounded, so a drop of exactly the tolerance (1.00 - 0.98) is not a float's 0.0200...02.
        if round(drop, 9) > config.tolerance:
            problems.append(
                f"{name}: pass rate {suite.pass_rate:.1%}, baseline {base.pass_rate:.1%} "
                f"(down {drop:.1%}, tolerance {config.tolerance:.1%})"
            )

    removed = sorted(set(baseline.suites) - set(current.suites))
    if removed:
        notes.append(f"categories in the baseline but not in this run: {', '.join(removed)}")

    fixed = sorted(set(baseline.summary.failed_critical) - set(current.summary.failed_critical))
    if fixed:
        notes.append(f"critical cases fixed since the baseline: {', '.join(fixed)}")

    return GateResult(passed=not problems, problems=problems, notes=notes)
