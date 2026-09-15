"""`evals`: run test sets, gate on a baseline, calibrate the judge, export results.

Exit codes: 0 when the gate passes, 1 when it fails, 2 when the config or a test
set is not usable.
"""

import argparse
import asyncio
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from eval_harness.cases import TestSetError, load_test_sets
from eval_harness.config import Config
from eval_harness.gate import check_gate
from eval_harness.judge import make_judge
from eval_harness.report import CaseResult, RunReport, _ms, markdown
from eval_harness.target import Target, http_target, load_adapter

MARKS = {"passed": "✓", "failed": "✗", "error": "!", "not_graded": "·"}


def _config(args: argparse.Namespace) -> Config:
    return Config.load(Path(args.config))


def _target(config: Config) -> Target:
    target = config.target
    if target.adapter is not None:
        # Adapters live in the project being tested, relative to the config file.
        sys.path.insert(0, str(config.path.parent.resolve()))
        sys.path.insert(0, str(Path.cwd()))
        return load_adapter(target.adapter)
    assert target.http is not None
    headers = {
        key: os.environ.get(value[1:], "") if value.startswith("$") else value
        for key, value in target.http.headers.items()
    }
    return http_target(target.http.url, headers=headers, timeout_seconds=config.timeout_seconds)


def _progress(result: CaseResult) -> None:
    mark = MARKS[result.status]
    latency = _ms(result.latency_ms) if result.latency_ms is not None else ""
    reason = f"  {result.first_reason()}" if result.counts_as_failure else ""
    print(f"{mark} {result.id:<12} {result.category:<22} {latency:>6}{reason}", file=sys.stderr)


def _publish(summary: str, path: Path) -> None:
    path.write_text(summary, encoding="utf-8")
    shutil.copyfile(path, path.with_name("latest.md"))
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)


def _load_baseline(path: Path | None) -> RunReport | None:
    if path is None or not path.is_file():
        return None
    return RunReport.load(path)


def cmd_validate(args: argparse.Namespace) -> int:
    config = _config(args)
    cases = load_test_sets(config.test_sets)
    print(f"{len(cases)} cases in {len(config.test_sets)} test set(s)")
    for label, counter in (
        ("category", Counter(c.category for c in cases)),
        ("severity", Counter(c.severity for c in cases)),
        ("grading", Counter(c.grading for c in cases)),
    ):
        print(f"  by {label}: " + ", ".join(f"{k} {v}" for k, v in sorted(counter.items())))
    rubric_cases = sum(c.needs_rubric for c in cases)
    if rubric_cases and config.judge is None:
        print(f"  note: {rubric_cases} rubric cases will not be graded without a judge")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from eval_harness.runner import report_path, run

    config = _config(args)
    cases = load_test_sets(config.test_sets)
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c.id in wanted]
    if args.category:
        cases = [c for c in cases if c.category in set(args.category)]
    if not cases:
        print("no cases match the filters", file=sys.stderr)
        return 2
    judge = None if args.no_judge or config.judge is None else make_judge(config.judge.model)

    report = asyncio.run(
        run(cases, target=_target(config), judge=judge, config=config, progress=_progress)
    )
    path = report_path(config, report)
    report.write(path)
    shutil.copyfile(path, config.reports_dir / "latest.json")

    filtered = bool(args.case or args.category)
    baseline_path = Path(args.baseline) if args.baseline else config.gate.baseline
    baseline = None if filtered else _load_baseline(baseline_path)
    gate = check_gate(report, baseline, config.gate)
    if filtered:
        gate.notes.append("filtered run: not compared with the baseline")
    summary = markdown(report, gate_lines=gate.lines, passed=gate.passed, baseline=baseline)
    _publish(summary, path.with_suffix(".md"))
    print(summary)
    print(f"Report: {path}", file=sys.stderr)
    return 0 if gate.passed or args.no_gate else 1


def cmd_gate(args: argparse.Namespace) -> int:
    config = _config(args)
    report = RunReport.load(Path(args.report))
    baseline = _load_baseline(Path(args.baseline) if args.baseline else config.gate.baseline)
    gate = check_gate(report, baseline, config.gate)
    print(markdown(report, gate_lines=gate.lines, passed=gate.passed, baseline=baseline))
    return 0 if gate.passed else 1


def cmd_baseline(args: argparse.Namespace) -> int:
    config = _config(args)
    if config.gate.baseline is None:
        print("set gate.baseline in the config first", file=sys.stderr)
        return 2
    source = Path(args.report) if args.report else config.reports_dir / "latest.json"
    report = RunReport.load(source)
    if report.summary.not_graded and report.run.judge_model is None:
        print("note: this report was graded without a judge", file=sys.stderr)
    config.gate.baseline.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, config.gate.baseline)
    print(f"Baseline is now {source} (run {report.run.id})")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    from eval_harness.calibrate import calibrate, load_labels
    from eval_harness.calibrate import markdown as calibration_markdown
    from eval_harness.rubric import JudgePrompt, sources_from_refs

    config = _config(args)
    if config.judge is None:
        print("calibration needs a judge in the config", file=sys.stderr)
        return 2
    judge_config = config.judge
    cases = {case.id: case for case in load_test_sets(config.test_sets)}
    report = asyncio.run(
        calibrate(
            load_labels(Path(args.labels)),
            cases,
            judge=make_judge(config.judge.model),
            prompt=JudgePrompt.load(config.judge.prompt),
            sources_for=lambda case: sources_from_refs(
                case, judge_config.sources_dir, judge_config.max_source_chars
            ),
            concurrency=config.concurrency,
        )
    )
    print(calibration_markdown(report))
    return 0


def cmd_export_langfuse(args: argparse.Namespace) -> int:
    from eval_harness.langfuse_export import export

    count = export(RunReport.load(Path(args.report)))
    print(f"Exported {count} cases to Langfuse")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="evals", description=__doc__)
    root.add_argument("-c", "--config", default="evals.yaml", help="path to evals.yaml")
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("validate", help="load the config and test sets without running anything")

    run = commands.add_parser("run", help="run the test sets, write a report and apply the gate")
    run.add_argument("--no-judge", action="store_true", help="skip rubric grading")
    run.add_argument("--no-gate", action="store_true", help="exit 0 even when the gate fails")
    run.add_argument("--baseline", help="compare with this report instead of gate.baseline")
    run.add_argument("--case", action="append", help="run only this case id (repeatable)")
    run.add_argument("--category", action="append", help="run only this category (repeatable)")

    gate = commands.add_parser("gate", help="apply the gate to a saved report")
    gate.add_argument("report")
    gate.add_argument("--baseline")

    baseline = commands.add_parser("baseline", help="make a report the new baseline")
    baseline.add_argument("report", nargs="?", help="defaults to the latest report")

    calibrate = commands.add_parser("calibrate", help="compare judge scores with human labels")
    calibrate.add_argument("--labels", required=True, help="CSV of human rubric scores")

    export = commands.add_parser("export-langfuse", help="send a report to Langfuse")
    export.add_argument("report")
    return root


HANDLERS = {
    "validate": cmd_validate,
    "run": cmd_run,
    "gate": cmd_gate,
    "baseline": cmd_baseline,
    "calibrate": cmd_calibrate,
    "export-langfuse": cmd_export_langfuse,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return HANDLERS[args.command](args)
    except (TestSetError, ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
