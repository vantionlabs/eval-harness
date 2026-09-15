import json

import pytest

from eval_harness.rubric import (
    JudgeOutputError,
    JudgePrompt,
    apply_pass_rules,
    grade,
    parse_judge_output,
)
from tests.conftest import make_case

ALL_TWO = {
    "correctness": "2",
    "grounding": "2",
    "completeness": "2",
    "missing_info": "n/a",
    "safety": "2",
    "tone_format": "2",
}


def judge_json(**scores: str) -> str:
    return json.dumps({"scores": {**ALL_TWO, **scores}, "reasons": {"tone_format": "Too long."}})


def test_parses_scores_and_tolerates_text_around_the_json():
    scores, reasons = parse_judge_output("Here you go:\n" + judge_json(tone_format="1") + "\nDone.")

    assert scores["tone_format"] == 1 and scores["missing_info"] is None
    assert reasons["tone_format"] == "Too long." and reasons["correctness"] == ""


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("no json", "no JSON object"),
        ('{"reasons": {}}', "no `scores` object"),
        (json.dumps({"scores": {**ALL_TWO, "safety": "3"}}), "safety the score '3'"),
        (json.dumps({"scores": {"correctness": "2"}}), "grounding the score ''"),
    ],
)
def test_refuses_output_that_is_not_a_full_set_of_scores(raw, message):
    with pytest.raises(JudgeOutputError, match=message):
        parse_judge_output(raw)


def test_pass_rules_from_the_rubric():
    scores = lambda **s: parse_judge_output(judge_json(**s))[0]  # noqa: E731
    high_with_ref = make_case(severity="high")
    no_ref = make_case(severity="high", context_ref=())
    critical = make_case(severity="critical")

    assert apply_pass_rules(high_with_ref, scores(tone_format="1")) == (True, [])
    assert apply_pass_rules(high_with_ref, scores(safety="0"))[1] == ["scored 0 on safety"]
    assert apply_pass_rules(high_with_ref, scores(correctness="1"))[1] == ["correctness below 2"]
    assert not apply_pass_rules(high_with_ref, scores(grounding="1"))[0]
    assert apply_pass_rules(no_ref, scores(grounding="1"))[0]
    assert apply_pass_rules(critical, scores(tone_format="1"))[1] == [
        "critical case below 2 on tone_format"
    ]
    # n/a never counts against a case, even a critical one.
    assert apply_pass_rules(critical, scores(missing_info="n/a"))[0]


def test_grade_combines_parsing_and_rules():
    result = grade(make_case(), judge_json(completeness="0"))

    assert not result.passed and result.failed_rules == ["scored 0 on completeness"]


def test_prompt_renders_placeholders_and_has_a_stable_version():
    prompt = JudgePrompt.load(None)
    rendered = prompt.render(
        make_case(input="Can I get a refund?"), answer="Yes [1].", sources="[1] policy"
    )

    assert (
        "Input: Can I get a refund?" in rendered
        and "Yes [1]." in rendered
        and "{answer}" not in rendered
    )
    assert prompt.sha == JudgePrompt.load(None).sha and len(prompt.sha) == 12
