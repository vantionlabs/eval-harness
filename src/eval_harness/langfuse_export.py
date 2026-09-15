"""Send a run report to Langfuse, to keep eval history next to production traces.

Each case becomes a trace named `eval <case id>`, grouped into one session per
run, with the input, the output, a boolean `eval_passed` score and one numeric
score per rubric criterion. Credentials come from the usual Langfuse environment
variables: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL.
"""

from eval_harness.report import RunReport


def export(report: RunReport) -> int:
    try:
        from langfuse import Langfuse, propagate_attributes
        from langfuse.api import ScoreDataType
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise RuntimeError("install the langfuse extra: uv add 'eval-harness[langfuse]'") from error

    client = Langfuse()
    run = report.run
    exported = 0
    for case in report.cases:
        if case.status == "not_graded":
            continue
        with (
            propagate_attributes(
                session_id=f"eval-{run.id}",
                version=run.target_version or None,
                tags=["eval", case.category, case.severity],
                trace_name=f"eval {case.id}",
                metadata={"target": run.target, "run_id": run.id},
            ),
            client.start_as_current_observation(
                name=f"eval {case.id}",
                as_type="span",
                input=case.input,
                output=case.output,
                metadata={
                    "status": case.status,
                    "checks": [check.model_dump() for check in case.checks],
                    "latency_ms": case.latency_ms,
                    "judge_model": run.judge_model,
                },
            ) as span,
        ):
            span.score_trace(
                name="eval_passed",
                value=1.0 if case.status == "passed" else 0.0,
                data_type=ScoreDataType.BOOLEAN,
                comment=case.first_reason() or None,
            )
            if case.rubric is not None:
                for criterion, score in case.rubric.scores.items():
                    if score is None:
                        continue
                    span.score_trace(
                        name=f"rubric_{criterion}",
                        value=float(score),
                        data_type=ScoreDataType.NUMERIC,
                        comment=case.rubric.reasons.get(criterion) or None,
                    )
        exported += 1
    client.flush()
    return exported
