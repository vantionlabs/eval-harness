import asyncio
import json
from pathlib import Path

from eval_harness.calibrate import calibrate, load_labels, markdown
from eval_harness.rubric import JudgePrompt
from tests.conftest import make_case
from tests.test_runner import SCORES, FakeJudge

COLUMNS = "id,labeler,answer,correctness,grounding,completeness,missing_info,safety,tone_format\n"


def test_compares_the_judge_with_agreed_labels_and_people_with_each_other(tmp_path: Path):
    labels = tmp_path / "labels.csv"
    labels.write_text(
        COLUMNS
        + "A,ana,answer a,2,2,2,n/a,2,2\n"
        + "A,ben,answer a,2,2,1,n/a,2,2\n"
        + "A,agreed,answer a,2,2,2,n/a,2,2\n"
        + "B,ana,answer b,2,2,2,n/a,0,2\n"
        + "C,ana,answer c,2,2,2,n/a,2,2\n"
        + "C,ben,answer c,2,2,2,n/a,2,1\n",
        encoding="utf-8",
    )
    cases = {cid: make_case(id=cid) for cid in ("A", "B", "C")}
    # A: the judge agrees. B: the judge misses a safety failure the person caught.
    judge = FakeJudge(replies=[json.dumps({"scores": SCORES}), json.dumps({"scores": SCORES})])

    report = asyncio.run(
        calibrate(
            load_labels(labels),
            cases,
            judge=judge,
            prompt=JudgePrompt.load(None),
            sources_for=lambda c: "",
        )
    )

    safety = report.criteria["safety"]
    assert (safety.compared, safety.exact, safety.judge_higher) == (2, 1, 1)
    assert report.criteria["completeness"].human_rate == 0.5
    assert report.pass_compared == 2 and report.judge_passed_human_failed == ["B"]
    assert report.skipped == ["C: several labelers and no `agreed` row"]
    text = markdown(report)
    assert "safety: the judge was more lenient than people 1 times." in text


def test_the_example_labels_file_loads():
    from tests.conftest import EXAMPLE

    labels = load_labels(EXAMPLE / "calibration-labels.csv")

    assert {label.labeler for label in labels} == {"ana", "ben", "agreed"}
    assert labels[0].scores["missing_info"] is None
