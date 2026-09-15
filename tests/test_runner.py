import asyncio
import json
from dataclasses import dataclass, field

import pytest

from eval_harness.cases import Case
from eval_harness.config import Config, JudgeConfig, TargetConfig
from eval_harness.judge import JudgeReply
from eval_harness.rubric import JudgePrompt
from eval_harness.runner import RetryPolicy, run, run_case, with_retries
from eval_harness.target import Response, RetryableError, Usage
from tests.conftest import make_case

SCORES = {
    "correctness": "2",
    "grounding": "2",
    "completeness": "2",
    "missing_info": "n/a",
    "safety": "2",
    "tone_format": "2",
}


def config(**overrides) -> Config:
    base = Config(
        test_sets=[],
        target=TargetConfig(name="t", adapter="x:y"),
        judge=JudgeConfig(model="fake:judge"),
        retries=2,
        timeout_seconds=5,
    )
    return base.model_copy(update=overrides)


@dataclass
class FakeJudge:
    replies: list[str]
    model: str = "fake:judge"
    prompts: list[str] = field(default_factory=list)

    async def score(self, prompt: str) -> JudgeReply:
        self.prompts.append(prompt)
        return JudgeReply(text=self.replies.pop(0), usage=Usage(100, 20, model=self.model))


def answering(text: str):
    async def target(case: Case) -> Response:
        return Response(output=text, usage=[Usage(10, 5, model="m", cost_usd=0.001)])

    return target


def test_with_retries_retries_retryable_failures_only():
    attempts = []

    async def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RetryableError("429")
        return "ok"

    policy = RetryPolicy(retries=3, timeout_seconds=1, base_delay_seconds=0)
    assert asyncio.run(with_retries(flaky, policy)) == ("ok", 3)

    async def broken():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        asyncio.run(with_retries(broken, policy))


def grade_one(case: Case, target, judge=None, **config_overrides):
    return asyncio.run(
        run_case(
            case,
            target=target,
            judge=judge,
            prompt=JudgePrompt.load(None),
            config=config(**config_overrides),
        )
    )


def test_a_target_that_raises_is_an_error_not_a_crash():
    async def target(case: Case) -> Response:
        raise KeyError("missing field")

    result = grade_one(make_case(), target)

    assert result.status == "error" and result.note == "target raised KeyError: 'missing field'"


def test_a_target_that_hangs_times_out():
    async def target(case: Case) -> Response:
        await asyncio.sleep(10)
        return Response(output="late")

    result = grade_one(make_case(), target, retries=0, timeout_seconds=0.05)

    assert result.status == "error" and "timed out" in result.note


def test_cases_that_fail_their_checks_never_reach_the_judge():
    judge = FakeJudge(replies=[])
    case = make_case(grading="both", must_include=("refund policy",))

    result = grade_one(case, answering("No idea."), judge)

    assert result.status == "failed" and result.note == "rubric skipped: checks failed"
    assert judge.prompts == []


def test_rubric_grading_retries_a_malformed_judge_reply_once():
    judge = FakeJudge(replies=["sorry, no json", json.dumps({"scores": SCORES, "reasons": {}})])

    result = grade_one(
        make_case(grading="rubric"), answering("Under our refund policy [1]."), judge
    )

    assert result.status == "passed"
    assert result.rubric is not None and result.rubric.scores["missing_info"] is None
    assert result.judge_cost.input_tokens == 200
    assert "Under our refund policy [1]." in judge.prompts[0]


def test_a_judge_that_keeps_failing_to_answer_properly_is_an_error():
    judge = FakeJudge(replies=["nope", "still nope"])

    result = grade_one(make_case(grading="rubric"), answering("x"), judge)

    assert result.status == "error" and result.note.startswith("judge output unusable")


def test_without_a_judge_rubric_cases_are_not_graded_and_both_cases_say_checks_only():
    rubric = grade_one(make_case(grading="rubric"), answering("x"))
    both = grade_one(make_case(grading="both"), answering("x"))

    assert rubric.status == "not_graded"
    assert both.status == "passed" and both.note == "checks only: no judge"


def test_run_aggregates_cases_cost_and_run_info():
    cases = [
        make_case(id="A", category="docs"),
        make_case(id="B", category="safety", must_include=("nope",)),
    ]

    report = asyncio.run(
        run(cases, target=answering("hello"), judge=None, config=config(judge=None))
    )

    assert report.summary.passed == 1 and report.summary.failed == 1
    assert report.suites["safety"].pass_rate == 0.0
    assert report.summary.cost.cost_usd == pytest.approx(0.002)
    assert report.run.judge_model is None and report.run.target == "t"
