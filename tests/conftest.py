from dataclasses import replace
from pathlib import Path

import pytest

from eval_harness.cases import Case
from eval_harness.target import Response, Source

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "support_assistant"


def make_case(**overrides: object) -> Case:
    base = Case(
        id="T-001",
        category="answer_from_docs",
        input="What is the refund policy?",
        context_ref=("kb/billing/refund-policy.md",),
        expected_behaviour="States the rule and cites it.",
        must_include=(),
        must_not_include=(),
        grading="deterministic",
        severity="high",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def make_response(
    output: str = "", sources: list[str] | None = None, **overrides: object
) -> Response:
    return Response(
        output=output,
        sources=[Source(id=s, text=f"text of {s}") for s in (sources or [])],
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE
