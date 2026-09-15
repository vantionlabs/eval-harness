from pathlib import Path

import pytest

from eval_harness.cases import TestSetError, load_test_set, load_test_sets
from tests.conftest import EXAMPLE


def test_loads_the_template_test_set_as_published():
    cases = load_test_set(EXAMPLE / "test-set.csv")

    assert len(cases) == 15
    refund = next(c for c in cases if c.id == "EVS-002")
    assert refund.must_include == ("refund policy", "[1]")
    assert refund.must_not_include == ("guaranteed refund", "full refund at any time")
    assert refund.severity == "critical" and refund.grading == "both"


def test_none_context_ref_means_no_source_and_semicolons_separate_several():
    cases = {c.id: c for c in load_test_set(EXAMPLE / "test-set.csv")}

    assert cases["EVS-004"].context_ref == ()
    assert cases["EVS-006"].context_ref == (
        "kb/billing/duplicate-charges.md",
        "kb/billing/seats.md",
    )


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


HEADER = (
    "id,category,input,context_ref,expected_behaviour,must_include,must_not_include,"
    "grading,severity\n"
)


def test_rejects_an_unknown_severity_with_the_line_number(tmp_path: Path):
    path = write(tmp_path, "set.csv", HEADER + "A-1,cat,hi,none,,,,deterministic,urgent\n")

    with pytest.raises(TestSetError, match=r"set.csv:2 \(A-1\): severity must be one of"):
        load_test_set(path)


def test_rejects_duplicate_ids_across_files(tmp_path: Path):
    first = write(tmp_path, "a.csv", HEADER + "A-1,cat,hi,none,,,,deterministic,low\n")
    second = write(tmp_path, "b.csv", HEADER + "A-1,cat,hello,none,,,,deterministic,low\n")

    with pytest.raises(TestSetError, match="duplicate id A-1"):
        load_test_sets([first, second])


def test_yaml_accepts_lists_and_the_optional_agent_columns(tmp_path: Path):
    write(tmp_path, "answer.schema.json", '{"type": "object"}')
    path = write(
        tmp_path,
        "set.yaml",
        """
cases:
  - id: AG-1
    category: tools
    input: Refund order 42
    severity: critical
    must_not_include: [refunded twice]
    expected_tools: [lookup_order, refund_order]
    forbidden_tools: delete_order
    json_schema: answer.schema.json
    citations: required
""",
    )

    [case] = load_test_set(path)

    assert case.expected_tools == ("lookup_order", "refund_order")
    assert case.forbidden_tools == ("delete_order",)
    assert case.json_schema == tmp_path / "answer.schema.json"
    assert case.citations_required
    assert case.grading == "deterministic"


def test_a_json_schema_that_does_not_exist_is_an_error_up_front(tmp_path: Path):
    path = write(
        tmp_path,
        "set.yaml",
        "- {id: A, category: c, input: i, severity: low, json_schema: nope.json}",
    )

    with pytest.raises(TestSetError, match="json_schema"):
        load_test_set(path)
