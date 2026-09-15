"""Deterministic checks: rules code can verify on every run, without a model.

Each check returns a `CheckResult`. A case passes its deterministic stage when
every check that applies to it passes. Checks that do not apply are left out,
so a report never shows a check as passed when it never ran.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

from eval_harness.cases import Case
from eval_harness.target import Response

CITATION = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def check_must_include(case: Case, response: Response) -> CheckResult | None:
    if not case.must_include:
        return None
    missing = [term for term in case.must_include if not _contains(response.output, term)]
    return CheckResult(
        "must_include", not missing, f"missing: {', '.join(missing)}" if missing else ""
    )


def check_must_not_include(case: Case, response: Response) -> CheckResult | None:
    if not case.must_not_include:
        return None
    found = [term for term in case.must_not_include if _contains(response.output, term)]
    return CheckResult(
        "must_not_include", not found, f"contains: {', '.join(found)}" if found else ""
    )


def _ref_matches(ref: str, source_id: str) -> bool:
    """`kb/billing/refund-policy.md` matches a source id of that path or its file name."""
    return source_id == ref or Path(source_id).name == Path(ref).name


def check_citations(case: Case, response: Response) -> CheckResult | None:
    """Every [n] points at a returned source, at least one is present, and each
    `context_ref` is among the cited sources."""
    if not case.citations_required:
        return None
    markers = sorted({int(n) for n in CITATION.findall(response.output)})
    if not markers:
        return CheckResult("citations", False, "no citation markers in the output")
    dangling = [n for n in markers if not 1 <= n <= len(response.sources)]
    if dangling:
        return CheckResult(
            "citations",
            False,
            f"markers {dangling} point past the {len(response.sources)} returned sources",
        )
    cited = [response.sources[n - 1].id for n in markers]
    uncited = [ref for ref in case.context_ref if not any(_ref_matches(ref, s) for s in cited)]
    if uncited:
        return CheckResult("citations", False, f"expected source not cited: {', '.join(uncited)}")
    return CheckResult("citations", True)


@cache
def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_json_schema(case: Case, response: Response) -> CheckResult | None:
    if case.json_schema is None:
        return None
    try:
        document = json.loads(response.output)
    except json.JSONDecodeError as error:
        return CheckResult("json_schema", False, f"output is not JSON: {error.msg}")
    try:
        jsonschema.validate(document, _schema(case.json_schema))
    except jsonschema.ValidationError as error:
        where = "/".join(str(part) for part in error.absolute_path) or "(root)"
        return CheckResult("json_schema", False, f"{where}: {error.message}")
    return CheckResult("json_schema", True)


def check_tools(case: Case, response: Response) -> CheckResult | None:
    if not case.expected_tools and not case.forbidden_tools:
        return None
    called = {call.name for call in response.tool_calls}
    missing = [name for name in case.expected_tools if name not in called]
    forbidden = [name for name in case.forbidden_tools if name in called]
    problems = []
    if missing:
        problems.append(f"not called: {', '.join(missing)}")
    if forbidden:
        problems.append(f"called forbidden: {', '.join(forbidden)}")
    return CheckResult("tool_calls", not problems, "; ".join(problems))


CHECKS = (
    check_must_include,
    check_must_not_include,
    check_citations,
    check_json_schema,
    check_tools,
)


def run_checks(case: Case, response: Response) -> list[CheckResult]:
    return [result for check in CHECKS if (result := check(case, response)) is not None]
