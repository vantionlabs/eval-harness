import json
from pathlib import Path

from eval_harness.checks import run_checks
from eval_harness.target import ToolCall
from tests.conftest import make_case, make_response


def by_name(results):
    return {r.name: r for r in results}


def test_required_and_forbidden_terms_ignore_case():
    case = make_case(must_include=("Refund Policy", "[1]"), must_not_include=("guaranteed refund",))

    good = by_name(run_checks(case, make_response("Under our refund policy you can [1].")))
    bad = by_name(run_checks(case, make_response("A GUARANTEED REFUND, always.")))

    assert good["must_include"].passed and good["must_not_include"].passed
    assert bad["must_include"].detail == "missing: Refund Policy, [1]"
    assert bad["must_not_include"].detail == "contains: guaranteed refund"


def test_checks_that_do_not_apply_are_left_out():
    assert run_checks(make_case(), make_response("anything")) == []


def test_citations_must_point_at_returned_sources_and_cite_the_expected_one():
    case = make_case(citations_required=True, context_ref=("kb/billing/refund-policy.md",))

    def check(output, sources):
        return by_name(run_checks(case, make_response(output, sources)))["citations"]

    assert (
        check("No markers here.", ["refund-policy.md"]).detail
        == "no citation markers in the output"
    )
    assert "point past the 1 returned sources" in check("See [2].", ["refund-policy.md"]).detail
    assert (
        "not cited: kb/billing/refund-policy.md"
        in check("See [1].", ["kb/billing/seats.md"]).detail
    )
    # A source id that is only the file name still matches the expected path.
    assert check("See [2].", ["kb/billing/seats.md", "refund-policy.md"]).passed


def test_json_schema(tmp_path: Path):
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["decision"],
                "properties": {"decision": {"enum": ["approve", "reject"]}},
            }
        )
    )
    case = make_case(json_schema=schema)

    def check(output):
        return by_name(run_checks(case, make_response(output)))["json_schema"]

    assert check("not json").detail.startswith("output is not JSON")
    assert check('{"decision": "maybe"}').detail.startswith("decision: 'maybe' is not one of")
    assert check('{"decision": "approve"}').passed


def test_expected_and_forbidden_tool_calls():
    case = make_case(
        expected_tools=("lookup_order", "refund_order"), forbidden_tools=("delete_order",)
    )
    response = make_response(tool_calls=[ToolCall("lookup_order"), ToolCall("delete_order")])

    result = by_name(run_checks(case, response))["tool_calls"]

    assert not result.passed
    assert result.detail == "not called: refund_order; called forbidden: delete_order"
