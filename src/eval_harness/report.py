"""What a run produced: a JSON report to keep, and a Markdown summary to read.

The JSON report is also the baseline format: the gate compares a run's report
with an earlier one, so keep the report of each release.
"""

import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from eval_harness.pricing import Cost

Status = Literal["passed", "failed", "not_graded", "error"]


class CheckRecord(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class RubricRecord(BaseModel):
    scores: dict[str, int | None]
    reasons: dict[str, str]
    passed: bool
    failed_rules: list[str] = Field(default_factory=list)


class CostRecord(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0
    unpriced_models: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, cost: Cost) -> "CostRecord":
        return cls(
            input_tokens=cost.input_tokens,
            output_tokens=cost.output_tokens,
            cost_usd=cost.cost_usd,
            unpriced_models=list(cost.unpriced_models),
        )

    def as_cost(self) -> Cost:
        return Cost(
            self.input_tokens, self.output_tokens, self.cost_usd, tuple(self.unpriced_models)
        )


class CaseResult(BaseModel):
    id: str
    category: str
    severity: str
    grading: str
    status: Status
    input: str
    output: str = ""
    checks: list[CheckRecord] = Field(default_factory=list)
    rubric: RubricRecord | None = None
    note: str = ""
    """Why a case was not graded, or what went wrong."""
    latency_ms: float | None = None
    attempts: int = 0
    target_cost: CostRecord = Field(default_factory=CostRecord)
    judge_cost: CostRecord = Field(default_factory=CostRecord)
    tool_calls: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @property
    def counts_as_failure(self) -> bool:
        # An error is a failure: a case that could not run proves nothing passed.
        return self.status in ("failed", "error")

    def first_reason(self) -> str:
        if self.status == "error":
            return self.note
        for check in self.checks:
            if not check.passed:
                return f"{check.name}: {check.detail}"
        if self.rubric is not None and not self.rubric.passed:
            reasons = [r for r in self.rubric.reasons.values() if r]
            rule = "; ".join(self.rubric.failed_rules)
            return f"rubric: {rule}" + (f" ({reasons[0]})" if reasons else "")
        return self.note


class Summary(BaseModel):
    cases: int
    passed: int
    failed: int
    errors: int
    not_graded: int
    pass_rate: float | None
    """Passed over graded cases. None when nothing in the group was graded."""
    failed_critical: list[str]
    cost: CostRecord
    latency_p50_ms: float | None
    latency_p95_ms: float | None


class RunInfo(BaseModel):
    id: str
    started_at: str
    finished_at: str
    target: str
    target_version: str = ""
    judge_model: str | None = None
    judge_prompt: str | None = None
    judge_prompt_sha: str | None = None
    git_sha: str | None = None
    harness_version: str


class RunReport(BaseModel):
    run: RunInfo
    summary: Summary
    suites: dict[str, Summary]
    """Per category. Named suites so a report reads the same as the gate's output."""
    severities: dict[str, Summary]
    cases: list[CaseResult]

    @classmethod
    def load(cls, path: Path) -> "RunReport":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[round(fraction * 100) - 1]


def summarise(results: Iterable[CaseResult]) -> Summary:
    results = list(results)
    passed = sum(r.status == "passed" for r in results)
    failed = sum(r.status == "failed" for r in results)
    errors = sum(r.status == "error" for r in results)
    not_graded = sum(r.status == "not_graded" for r in results)
    graded = passed + failed + errors
    cost = Cost()
    for result in results:
        cost = cost + result.target_cost.as_cost() + result.judge_cost.as_cost()
    latencies = [r.latency_ms for r in results if r.latency_ms is not None]
    return Summary(
        cases=len(results),
        passed=passed,
        failed=failed,
        errors=errors,
        not_graded=not_graded,
        pass_rate=passed / graded if graded else None,
        failed_critical=sorted(
            r.id for r in results if r.severity == "critical" and r.counts_as_failure
        ),
        cost=CostRecord.of(cost),
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
    )


def group(results: list[CaseResult], key: str) -> dict[str, Summary]:
    keys = sorted({getattr(r, key) for r in results})
    return {k: summarise(r for r in results if getattr(r, key) == k) for k in keys}


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _money(cost: CostRecord) -> str:
    return "unknown" if cost.cost_usd is None else f"${cost.cost_usd:.4f}"


def _ms(value: float | None) -> str:
    return (
        "n/a" if value is None else (f"{value / 1000:.1f}s" if value >= 1000 else f"{value:.0f}ms")
    )


def markdown(
    report: RunReport, *, gate_lines: list[str], passed: bool, baseline: RunReport | None
) -> str:
    run = report.run
    verdict = "✅ No regressions" if passed else "❌ Eval gate failed"
    target = f"`{run.target}`" + (f" {run.target_version}" if run.target_version else "")
    judge = f"`{run.judge_model}` (prompt {run.judge_prompt_sha})" if run.judge_model else "none"
    lines = [
        f"## {verdict}",
        "",
        f"Target {target} · judge {judge} · run `{run.id}`",
        "",
    ]
    if gate_lines:
        lines += [f"- {line}" for line in gate_lines] + [""]

    lines += [
        "| Category | Cases | Pass rate | Baseline | Critical failures | Cost | p50 | p95 |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for name, suite in [*report.suites.items(), ("**All**", report.summary)]:
        base = (
            baseline.summary
            if baseline and name == "**All**"
            else baseline.suites.get(name)
            if baseline
            else None
        )
        critical = ", ".join(suite.failed_critical) or "none"
        lines.append(
            f"| {name} | {suite.cases} | {_rate(suite.pass_rate)} | "
            f"{_rate(base.pass_rate) if base else 'n/a'} | {critical} | {_money(suite.cost)} | "
            f"{_ms(suite.latency_p50_ms)} | {_ms(suite.latency_p95_ms)} |"
        )

    summary = report.summary
    lines += [
        "",
        f"{summary.passed} passed, {summary.failed} failed, {summary.errors} errors, "
        f"{summary.not_graded} not graded. Tokens: {summary.cost.input_tokens:,} in, "
        f"{summary.cost.output_tokens:,} out.",
    ]
    if summary.cost.unpriced_models:
        lines.append(
            f"Cost is unknown: no price configured for {', '.join(summary.cost.unpriced_models)}."
        )

    failures = [r for r in report.cases if r.counts_as_failure]
    if failures:
        lines += [
            "",
            "### Failures",
            "",
            "| Case | Category | Severity | Reason |",
            "| --- | --- | --- | --- |",
        ]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for result in sorted(failures, key=lambda r: (order.get(r.severity, 9), r.id)):
            reason = result.first_reason().replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {result.id} | {result.category} | {result.severity} | {reason} |")

    not_graded = [r for r in report.cases if r.status == "not_graded"]
    if not_graded:
        ids = ", ".join(r.id for r in not_graded)
        lines += ["", f"Not graded ({len(not_graded)}): {ids} ({not_graded[0].note})."]
    return "\n".join(lines) + "\n"
