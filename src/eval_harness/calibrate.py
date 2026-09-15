"""Calibration: how closely does the judge agree with people?

A labels CSV holds answers scored by hand with the rubric:

    id, labeler, answer, correctness, grounding, completeness, missing_info, safety, tone_format

`id` refers to a case in the test sets. Scores are 0, 1, 2 or n/a. When two
people score the same answer, add a row with `labeler` set to `agreed` holding
the scores they settled on; the judge is compared with that row. With a single
labeler, the judge is compared with theirs.

The report shows, per criterion, how often the judge matched the people, and in
which direction it was wrong. A judge that is too lenient on safety is worse than
one that is too strict on tone, so read the direction, not only the rate.
"""

import asyncio
import csv
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from eval_harness.cases import Case
from eval_harness.judge import Judge
from eval_harness.rubric import (
    CRITERIA,
    SCORE_VALUES,
    JudgePrompt,
    Score,
    apply_pass_rules,
    parse_judge_output,
)
from eval_harness.runner import RetryPolicy, with_retries

AGREED = "agreed"


@dataclass(frozen=True)
class Label:
    case_id: str
    labeler: str
    answer: str
    scores: dict[str, Score]


@dataclass
class CriterionAgreement:
    compared: int = 0
    exact: int = 0
    judge_higher: int = 0
    """The judge scored more generously than people: the dangerous direction."""
    judge_lower: int = 0
    human_pairs: int = 0
    human_exact: int = 0

    @property
    def judge_rate(self) -> float | None:
        return self.exact / self.compared if self.compared else None

    @property
    def human_rate(self) -> float | None:
        return self.human_exact / self.human_pairs if self.human_pairs else None


@dataclass
class CalibrationReport:
    criteria: dict[str, CriterionAgreement]
    pass_compared: int = 0
    pass_agreed: int = 0
    judge_passed_human_failed: list[str] = field(default_factory=list)
    judge_failed_human_passed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    judge_model: str = ""
    judge_prompt_sha: str = ""


def load_labels(path: Path) -> list[Label]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    labels = []
    for line, row in enumerate(rows, start=2):
        scores: dict[str, Score] = {}
        for name in CRITERIA:
            value = (row.get(name) or "").strip().lower()
            if value not in SCORE_VALUES:
                raise ValueError(f"{path}:{line}: {name} must be 0, 1, 2 or n/a, got {value!r}")
            scores[name] = None if value == "n/a" else int(value)  # type: ignore[assignment]
        labels.append(
            Label(
                case_id=(row.get("id") or "").strip(),
                labeler=(row.get("labeler") or "").strip() or "labeler",
                answer=row.get("answer") or "",
                scores=scores,
            )
        )
    return labels


def _compare(stats: CriterionAgreement, judge: Score, human: Score) -> None:
    stats.compared += 1
    if judge == human:
        stats.exact += 1
    elif judge is not None and human is not None:
        if judge > human:
            stats.judge_higher += 1
        else:
            stats.judge_lower += 1


async def calibrate(
    labels: list[Label],
    cases: dict[str, Case],
    *,
    judge: Judge,
    prompt: JudgePrompt,
    sources_for: Callable[[Case], str],
    concurrency: int = 4,
    policy: RetryPolicy | None = None,
) -> CalibrationReport:
    report = CalibrationReport(
        criteria={name: CriterionAgreement() for name in CRITERIA},
        judge_model=judge.model,
        judge_prompt_sha=prompt.sha,
    )
    by_case: dict[str, list[Label]] = defaultdict(list)
    for label in labels:
        by_case[label.case_id].append(label)

    # How often people agree with each other sets the bar for the judge.
    for group in by_case.values():
        people = [label for label in group if label.labeler != AGREED]
        for i, first in enumerate(people):
            for second in people[i + 1 :]:
                for name in CRITERIA:
                    stats = report.criteria[name]
                    stats.human_pairs += 1
                    stats.human_exact += first.scores[name] == second.scores[name]

    reference: dict[str, Label] = {}
    for case_id, group in by_case.items():
        if case_id not in cases:
            report.skipped.append(f"{case_id}: not in the test sets")
            continue
        agreed = [label for label in group if label.labeler == AGREED]
        if agreed:
            reference[case_id] = agreed[0]
        elif len(group) == 1:
            reference[case_id] = group[0]
        else:
            report.skipped.append(f"{case_id}: several labelers and no `agreed` row")

    semaphore = asyncio.Semaphore(concurrency)
    policy = policy or RetryPolicy()

    async def judged(case_id: str, label: Label) -> tuple[str, dict[str, Score] | None]:
        case = cases[case_id]
        rendered = prompt.render(case, answer=label.answer, sources=sources_for(case))
        async with semaphore:
            try:
                reply, _ = await with_retries(lambda: judge.score(rendered), policy)
                scores, _ = parse_judge_output(reply.text)
            except Exception as error:
                report.skipped.append(f"{case_id}: judge failed ({error})")
                return case_id, None
        return case_id, scores

    results = await asyncio.gather(*(judged(cid, label) for cid, label in reference.items()))
    for case_id, judge_scores in sorted(results):
        if judge_scores is None:
            continue
        human = reference[case_id]
        for name in CRITERIA:
            _compare(report.criteria[name], judge_scores[name], human.scores[name])
        judge_pass, _ = apply_pass_rules(cases[case_id], judge_scores)
        human_pass, _ = apply_pass_rules(cases[case_id], human.scores)
        report.pass_compared += 1
        if judge_pass == human_pass:
            report.pass_agreed += 1
        elif judge_pass:
            report.judge_passed_human_failed.append(case_id)
        else:
            report.judge_failed_human_passed.append(case_id)
    return report


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def markdown(report: CalibrationReport) -> str:
    lines = [
        "## Judge calibration",
        "",
        f"Judge `{report.judge_model}`, prompt {report.judge_prompt_sha}.",
        "",
        "| Criterion | Compared | Judge agrees | People agree | Judge higher | Judge lower |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    warnings = []
    for name, stats in report.criteria.items():
        lines.append(
            f"| {name} | {stats.compared} | {_rate(stats.judge_rate)} | {_rate(stats.human_rate)} "
            f"| {stats.judge_higher} | {stats.judge_lower} |"
        )
        if (
            stats.judge_rate is not None
            and stats.human_rate is not None
            and stats.judge_rate < stats.human_rate
        ):
            warnings.append(
                f"{name}: the judge agrees with people less often than people agree with "
                "each other. Tighten the prompt or the criterion before relying on it."
            )
        if name in ("safety", "correctness") and stats.judge_higher:
            warnings.append(
                f"{name}: the judge was more lenient than people {stats.judge_higher} times."
            )

    rate = report.pass_agreed / report.pass_compared if report.pass_compared else None
    lines += ["", f"Pass or fail agreement: {_rate(rate)} of {report.pass_compared} answers."]
    if report.judge_passed_human_failed:
        lines.append(f"Judge passed, people failed: {', '.join(report.judge_passed_human_failed)}.")
    if report.judge_failed_human_passed:
        lines.append(f"Judge failed, people passed: {', '.join(report.judge_failed_human_passed)}.")
    if warnings:
        lines += ["", "### Warnings", "", *[f"- {w}" for w in warnings]]
    if report.skipped:
        lines += ["", "### Skipped", "", *[f"- {s}" for s in report.skipped]]
    return "\n".join(lines) + "\n"
