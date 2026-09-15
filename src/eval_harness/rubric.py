"""Rubric grading: the criteria, the judge prompt, and the pass rules.

The criteria and pass rules are those of the eval grading rubric in
github.com/vantionlabs/eval-test-set-template. The judge only scores; whether a
case passes is decided here, in code, so the rules can change without paying
for every grade again.
"""

import hashlib
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from eval_harness.cases import Case

Score = Literal[0, 1, 2] | None
"""0, 1 or 2, or None for a criterion that does not apply (`n/a`)."""

CRITERIA: tuple[str, ...] = (
    "correctness",
    "grounding",
    "completeness",
    "missing_info",
    "safety",
    "tone_format",
)

SCORE_VALUES = ("0", "1", "2", "n/a")

# The judge must answer in this shape. Scores are strings so the schema stays a
# plain enum, which every provider's structured output mode accepts.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                name: {"type": "string", "enum": list(SCORE_VALUES)} for name in CRITERIA
            },
            "required": list(CRITERIA),
            "additionalProperties": False,
        },
        "reasons": {
            "type": "object",
            "properties": {name: {"type": "string"} for name in CRITERIA},
            "required": list(CRITERIA),
            "additionalProperties": False,
        },
    },
    "required": ["scores", "reasons"],
    "additionalProperties": False,
}


class JudgeOutputError(ValueError):
    """The judge returned something other than the scores it was asked for."""


@dataclass(frozen=True)
class RubricGrade:
    scores: dict[str, Score]
    reasons: dict[str, str]
    passed: bool
    failed_rules: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JudgePrompt:
    text: str
    source: str

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def load(cls, path: Path | None) -> "JudgePrompt":
        if path is None:
            text = (resources.files("eval_harness") / "prompts" / "judge.md").read_text("utf-8")
            return cls(text=text, source="eval_harness/prompts/judge.md")
        return cls(text=path.read_text(encoding="utf-8"), source=str(path))

    def render(self, case: Case, *, answer: str, sources: str) -> str:
        values = {
            "input": case.input,
            "expected_behaviour": case.expected_behaviour or "(none given)",
            "severity": case.severity,
            "sources": sources or "(no sources)",
            "answer": answer,
        }
        text = self.text
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        return text


def parse_judge_output(raw: str) -> tuple[dict[str, Score], dict[str, str]]:
    """Read the judge's JSON, tolerating text around it but nothing missing from it."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        raise JudgeOutputError("no JSON object in the judge output")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as error:
        raise JudgeOutputError(f"judge output is not valid JSON: {error.msg}") from error

    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raise JudgeOutputError("judge output has no `scores` object")
    raw_reasons = data.get("reasons") if isinstance(data.get("reasons"), dict) else {}

    scores: dict[str, Score] = {}
    for name in CRITERIA:
        value = str(raw_scores.get(name, "")).strip().lower()
        if value not in SCORE_VALUES:
            raise JudgeOutputError(f"judge gave {name} the score {value!r}")
        scores[name] = None if value == "n/a" else int(value)  # type: ignore[assignment]
    reasons = {name: str(raw_reasons.get(name, "") or "") for name in CRITERIA}
    return scores, reasons


def apply_pass_rules(case: Case, scores: dict[str, Score]) -> tuple[bool, list[str]]:
    """The rubric's pass rules. Returns whether the case passed, and each rule it broke."""
    failed: list[str] = []
    zeros = [name for name, score in scores.items() if score == 0]
    if zeros:
        failed.append(f"scored 0 on {', '.join(zeros)}")
    if scores.get("correctness") != 2:
        failed.append("correctness below 2")
    if case.context_ref and scores.get("grounding") != 2:
        failed.append("grounding below 2 on a case with a context_ref")
    if case.severity == "critical":
        below = [name for name, score in scores.items() if score is not None and score < 2]
        if below:
            failed.append(f"critical case below 2 on {', '.join(below)}")
    return not failed, failed


def grade(case: Case, raw_judge_output: str) -> RubricGrade:
    scores, reasons = parse_judge_output(raw_judge_output)
    passed, failed_rules = apply_pass_rules(case, scores)
    return RubricGrade(scores=scores, reasons=reasons, passed=passed, failed_rules=failed_rules)


def sources_from_refs(case: Case, sources_dir: Path | None, max_chars: int = 20_000) -> str:
    """The case's `context_ref` files, numbered for the judge prompt."""
    if sources_dir is None:
        return ""
    parts = []
    for index, ref in enumerate(case.context_ref, start=1):
        path = sources_dir / ref
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "(missing)"
        parts.append(f"[{index}] {ref}\n{text[:max_chars]}")
    return "\n\n".join(parts)
