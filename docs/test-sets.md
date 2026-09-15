# Test sets

A test set is a CSV or YAML file of cases. Each case is one input, what a good
response has to do, and how to check it. List the files under `test_sets` in
`evals.yaml`; ids must be unique across all of them.

## Columns

The first eleven are the columns of the
[eval test set template](https://github.com/vantionlabs/eval-test-set-template).

| Column | Required | What it holds |
| --- | --- | --- |
| `id` | yes | A stable id. Never reuse one: runs are compared by id. |
| `category` | yes | The kind of case. Pass rates and the gate work per category. |
| `input` | yes | The exact input sent to your application. |
| `context_ref` | | The source or sources the answer should draw on, separated by `\|` or `;`, or `none`. |
| `expected_behaviour` | | What a good response does, in words a reviewer can judge. The judge reads it. |
| `must_include` | | Terms that must appear, separated by `\|`. Case-insensitive. |
| `must_not_include` | | Terms that must not appear. |
| `grading` | | `deterministic` (the default), `rubric` or `both`. |
| `severity` | yes | `critical`, `high`, `medium` or `low`. A new critical failure fails the gate. |
| `source` | | Where the case came from: a support ticket, a production trace, an incident. |
| `added_on` | | When it was added. |
| `citations` | | `required` to check citation markers. See below. |
| `json_schema` | | A JSON schema file the output must validate against, relative to the test set. |
| `expected_tools` | | Tools the application must call, separated by `\|`. |
| `forbidden_tools` | | Tools it must not call. |

In YAML, list columns can be lists:

```yaml
cases:
  - id: AGENT-014
    category: refunds
    input: Refund order 1042, the customer was charged twice.
    expected_tools: [lookup_order, refund_order]
    forbidden_tools: [delete_order]
    must_not_include: [refunded twice]
    severity: critical
```

## Grading

- **`deterministic`**: the checks below decide the case.
- **`rubric`**: the judge scores the response on the rubric, and the pass rules
  decide. Needs a judge; without one the case is reported as not graded.
- **`both`**: the checks run first. If they fail, the case fails and the judge is
  not called. If they pass, the judge decides. Without a judge the checks decide,
  and the case is marked "checks only".

## Checks

Checks only run when their column has a value, so a report never shows a check
as passed that did not run.

- **`must_include` / `must_not_include`.** Plain substring matches, ignoring case.
  Keep terms short and specific: a citation marker, a product term, a phrase that
  would signal a leak. Common words make the check fragile.
- **`citations`.** The output must contain at least one `[n]` marker, every marker
  must point at one of the sources your adapter returned (`[1]` is the first),
  and each `context_ref` must be among the cited sources. A source matches a
  reference by full path or by file name.
- **`json_schema`.** The whole output must be JSON and validate against the schema.
- **`expected_tools` / `forbidden_tools`.** Compared with the names in the
  response's `tool_calls`. For an agent, a correct final message after a wrong
  tool call is still a failure.

## Writing good cases

- Copy inputs from real conversations where you can, and record where they came
  from in `source`.
- Describe behaviour in `expected_behaviour`, not a reference answer. Wording
  changes between runs; the behaviour you want does not.
- Cover the cases that break things: questions the sources do not answer,
  ambiguous inputs, prompt injection, other users' data, other languages.
- When something goes wrong in production, add it as a case before fixing it, with
  `source: incident`. Then it cannot come back unnoticed.
- Keep categories consistent. A drop in one category points at the cause; a drop
  in the overall rate does not.
