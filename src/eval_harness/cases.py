"""Test cases, loaded from CSV or YAML files in the eval test set template format.

The columns are those of github.com/vantionlabs/eval-test-set-template:

    id, category, input, context_ref, expected_behaviour, must_include,
    must_not_include, grading, severity, source, added_on

plus optional columns for checks the template leaves out:

    citations        `required` to check that [n] markers point at returned sources
    json_schema      path to a JSON schema the output must validate against,
                     relative to the test set file
    expected_tools   tool names the target must call, separated by `|`
    forbidden_tools  tool names the target must not call, separated by `|`

In CSV, list columns hold values separated by `|`. In YAML they can also be lists.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Severity = Literal["critical", "high", "medium", "low"]
Grading = Literal["deterministic", "rubric", "both"]

SEVERITIES: tuple[Severity, ...] = ("critical", "high", "medium", "low")
GRADINGS: tuple[Grading, ...] = ("deterministic", "rubric", "both")
REQUIRED_COLUMNS = ("id", "category", "input", "severity")


class TestSetError(ValueError):
    """A test set file that cannot be used as written."""

    __test__ = False  # not a pytest test class, despite the name


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    input: str
    context_ref: tuple[str, ...]
    expected_behaviour: str
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    grading: Grading
    severity: Severity
    source: str = ""
    added_on: str = ""
    citations_required: bool = False
    json_schema: Path | None = None
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    test_set: str = ""

    @property
    def needs_rubric(self) -> bool:
        return self.grading in ("rubric", "both")

    @property
    def needs_deterministic(self) -> bool:
        return self.grading in ("deterministic", "both")


def _list(value: Any, *, separators: str = "|") -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value)
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return tuple(part.strip() for part in text.split(separators[0]) if part.strip())


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _case(row: dict[str, Any], *, path: Path, line: int) -> Case:
    where = f"{path}:{line}"
    missing = [column for column in REQUIRED_COLUMNS if not _text(row, column)]
    if missing:
        raise TestSetError(f"{where}: missing {', '.join(missing)}")

    case_id = _text(row, "id")
    severity = _text(row, "severity").lower()
    if severity not in SEVERITIES:
        raise TestSetError(f"{where} ({case_id}): severity must be one of {', '.join(SEVERITIES)}")
    grading = (_text(row, "grading") or "deterministic").lower()
    if grading not in GRADINGS:
        raise TestSetError(f"{where} ({case_id}): grading must be one of {', '.join(GRADINGS)}")

    citations = _text(row, "citations").lower()
    if citations not in ("", "required", "none"):
        raise TestSetError(f"{where} ({case_id}): citations must be `required` or empty")

    schema = _text(row, "json_schema")
    schema_path = (path.parent / schema) if schema else None
    if schema_path is not None and not schema_path.is_file():
        raise TestSetError(f"{where} ({case_id}): json_schema {schema_path} does not exist")

    refs = _list(row.get("context_ref"), separators="|;")
    return Case(
        id=case_id,
        category=_text(row, "category"),
        input=str(row.get("input", "")),
        context_ref=tuple(ref for ref in refs if ref.lower() != "none"),
        expected_behaviour=_text(row, "expected_behaviour"),
        must_include=_list(row.get("must_include")),
        must_not_include=_list(row.get("must_not_include")),
        grading=grading,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        source=_text(row, "source"),
        added_on=_text(row, "added_on"),
        citations_required=citations == "required",
        json_schema=schema_path,
        expected_tools=_list(row.get("expected_tools")),
        forbidden_tools=_list(row.get("forbidden_tools")),
        test_set=str(path),
    )


def load_test_set(path: Path) -> list[Case]:
    """Load one CSV or YAML file. YAML holds a list of cases, or `{cases: [...]}`."""
    if not path.is_file():
        raise TestSetError(f"{path}: no such test set")

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            rows: list[dict[str, Any]] = list(csv.DictReader(handle))
        first_line = 2  # line 1 is the header
    elif path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "cases" in data:
            data = data["cases"]
        if not isinstance(data, list):
            raise TestSetError(f"{path}: expected a list of cases")
        rows = [row for row in data if isinstance(row, dict)]
        first_line = 1
    else:
        raise TestSetError(f"{path}: test sets must be .csv, .yaml or .yml")

    return [_case(row, path=path, line=first_line + index) for index, row in enumerate(rows)]


def load_test_sets(paths: list[Path]) -> list[Case]:
    """Load every file, refusing duplicate ids across them: ids are how runs are compared."""
    cases: list[Case] = []
    seen: dict[str, str] = {}
    for path in paths:
        for case in load_test_set(path):
            if case.id in seen:
                raise TestSetError(f"{path}: duplicate id {case.id} (also in {seen[case.id]})")
            seen[case.id] = str(path)
            cases.append(case)
    if not cases:
        raise TestSetError("no cases found in the configured test sets")
    return cases
