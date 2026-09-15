"""Running a test set: call the target for each case, check, grade, and collect results.

Cases run concurrently up to `concurrency`. A call that fails with a
`RetryableError` or times out is retried with exponential backoff. Any other
exception is recorded against the case as an error, and the run carries on: one
broken case should not hide the results of the rest.
"""

import asyncio
import random
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from eval_harness.cases import Case
from eval_harness.checks import run_checks
from eval_harness.config import Config
from eval_harness.judge import Judge
from eval_harness.pricing import cost_of
from eval_harness.report import (
    CaseResult,
    CheckRecord,
    CostRecord,
    RubricRecord,
    RunInfo,
    RunReport,
    group,
    summarise,
)
from eval_harness.rubric import JudgeOutputError, JudgePrompt, grade, sources_from_refs
from eval_harness.target import Response, RetryableError, Target

Progress = Callable[[CaseResult], None]


@dataclass(frozen=True)
class RetryPolicy:
    retries: int = 3
    timeout_seconds: float = 120
    base_delay_seconds: float = 1.0


async def with_retries[T](make: Callable[[], Awaitable[T]], policy: RetryPolicy) -> tuple[T, int]:
    """Run `make()` with a timeout, retrying retryable failures. Returns the result and attempts."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return await asyncio.wait_for(make(), policy.timeout_seconds), attempt
        except (RetryableError, TimeoutError):
            if attempt > policy.retries:
                raise
            delay = policy.base_delay_seconds * 2 ** (attempt - 1)
            await asyncio.sleep(delay + random.uniform(0, delay / 2))


def _sources_text(case: Case, response: Response, config: Config) -> str:
    if response.sources:
        return "\n\n".join(
            f"[{index}] {source.id}\n{source.text}".rstrip()
            for index, source in enumerate(response.sources, start=1)
        )
    if config.judge is None:
        return ""
    return sources_from_refs(case, config.judge.sources_dir, config.judge.max_source_chars)


async def run_case(
    case: Case,
    *,
    target: Target,
    judge: Judge | None,
    prompt: JudgePrompt,
    config: Config,
) -> CaseResult:
    policy = RetryPolicy(retries=config.retries, timeout_seconds=config.timeout_seconds)
    base = CaseResult(
        id=case.id,
        category=case.category,
        severity=case.severity,
        grading=case.grading,
        status="error",
        input=case.input,
    )

    started = time.perf_counter()
    try:
        response, attempts = await with_retries(lambda: target(case), policy)
    except TimeoutError:
        return base.model_copy(
            update={"note": f"target timed out after {config.retries + 1} attempts"}
        )
    except Exception as error:
        return base.model_copy(update={"note": f"target raised {type(error).__name__}: {error}"})
    latency_ms = (time.perf_counter() - started) * 1000

    checks = run_checks(case, response) if case.needs_deterministic else []
    deterministic_passed = all(check.passed for check in checks)
    result = base.model_copy(
        update={
            "output": response.output,
            "checks": [CheckRecord(name=c.name, passed=c.passed, detail=c.detail) for c in checks],
            "latency_ms": latency_ms,
            "attempts": attempts,
            "target_cost": CostRecord.of(cost_of(response.usage, config.prices)),
            "tool_calls": [call.name for call in response.tool_calls],
            "sources": [source.id for source in response.sources],
        }
    )

    if not case.needs_rubric:
        return result.model_copy(update={"status": "passed" if deterministic_passed else "failed"})
    if not deterministic_passed:
        # Grading an answer that already broke a hard rule would only spend money.
        return result.model_copy(
            update={"status": "failed", "note": "rubric skipped: checks failed"}
        )
    if judge is None:
        if case.grading == "both":
            # The checks ran and passed; say plainly that the rubric half did not.
            return result.model_copy(update={"status": "passed", "note": "checks only: no judge"})
        return result.model_copy(update={"status": "not_graded", "note": "no judge configured"})

    rendered = prompt.render(
        case, answer=response.output, sources=_sources_text(case, response, config)
    )
    judge_usage = []
    # One extra attempt for a malformed reply, on top of retries for provider errors.
    for parse_attempt in range(2):
        try:
            reply, _ = await with_retries(lambda: judge.score(rendered), policy)
        except Exception as error:
            return result.model_copy(
                update={
                    "note": f"judge failed: {type(error).__name__}: {error}",
                    "judge_cost": CostRecord.of(cost_of(judge_usage, config.prices)),
                }
            )
        judge_usage.append(reply.usage)
        try:
            rubric = grade(case, reply.text)
        except JudgeOutputError as error:
            if parse_attempt == 1:
                return result.model_copy(
                    update={
                        "note": f"judge output unusable: {error}",
                        "judge_cost": CostRecord.of(cost_of(judge_usage, config.prices)),
                    }
                )
            continue
        return result.model_copy(
            update={
                "status": "passed" if rubric.passed else "failed",
                "rubric": RubricRecord(
                    scores=dict(rubric.scores),
                    reasons=rubric.reasons,
                    passed=rubric.passed,
                    failed_rules=rubric.failed_rules,
                ),
                "judge_cost": CostRecord.of(cost_of(judge_usage, config.prices)),
            }
        )
    raise AssertionError("unreachable")


def _git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _harness_version() -> str:
    try:
        return version("eval-harness")
    except PackageNotFoundError:
        return "0.0.0"


async def run(
    cases: list[Case],
    *,
    target: Target,
    judge: Judge | None,
    config: Config,
    progress: Progress | None = None,
) -> RunReport:
    prompt = JudgePrompt.load(config.judge.prompt if config.judge else None)
    semaphore = asyncio.Semaphore(config.concurrency)
    started_at = datetime.now(UTC)

    async def one(case: Case) -> CaseResult:
        async with semaphore:
            result = await run_case(case, target=target, judge=judge, prompt=prompt, config=config)
        if progress is not None:
            progress(result)
        return result

    results = await asyncio.gather(*(one(case) for case in cases))
    return RunReport(
        run=RunInfo(
            id=started_at.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6],
            started_at=started_at.isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            target=config.target.name,
            target_version=config.target.version,
            judge_model=judge.model if judge else None,
            judge_prompt=prompt.source if judge else None,
            judge_prompt_sha=prompt.sha if judge else None,
            git_sha=_git_sha(),
            harness_version=_harness_version(),
        ),
        summary=summarise(results),
        suites=group(results, "category"),
        severities=group(results, "severity"),
        cases=results,
    )


def report_path(config: Config, report: RunReport) -> Path:
    return config.reports_dir / f"{report.run.id}.json"
