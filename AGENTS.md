# Conventions for AI coding agents (and humans)

An eval harness is only worth running if its results can be trusted. These rules
keep it honest: a result never claims more than was checked.

## Results

- Never report a check as passed when it did not run. Checks that do not apply to
  a case are left out of its results, not recorded as passing.
- An error is a failure. A case whose target or judge could not be run counts
  against the pass rate and, when critical, against the gate.
- Unknown is not zero. A model without a configured price reports an unknown cost,
  never $0. Do not add a default price list.
- A run graded one way is never compared with a baseline graded another way
  (judge versus no judge). The gate refuses, and must keep refusing.

## Grading

- The judge only scores. Pass rules live in `rubric.apply_pass_rules`, in code, so
  they can change without regrading. Do not ask the judge whether a case passed.
- The criteria names, the output schema and the pass rules move together. Change
  one and change the others, the default prompt, and `docs/judge.md`.
- Deterministic checks run before the judge, and a case that fails them is never
  sent to the judge.
- Every report records the judge model and the prompt hash. Keep it that way:
  that record is what makes an old report comparable, or not.

## Test sets

- The template columns (`id` through `added_on`) mean what they mean in
  github.com/vantionlabs/eval-test-set-template. New behaviour gets a new optional
  column, documented in `cases.py` and `docs/test-sets.md`.
- A test set that cannot be used fails loudly with the file and line, before any
  case runs. Never skip a bad row.

## Code

- Python 3.12, uv, ruff (lint and format), pyright, pytest.
- Provider SDKs are optional extras, imported inside the judge that needs them.
  The core harness must import without them.
- Both provider SDKs are built on `httpx2`. Tests fake their HTTP layer with
  `httpx2.MockTransport`; the HTTP target uses `httpx`.
- Tests never call a real model or network. Fake the judge (`tests/test_runner.py`
  has one) or the transport.
- `examples/support_assistant` runs in CI with `--no-judge` against its committed
  `baseline.json`. If you change the example or the report format, regenerate the
  baseline with `evals baseline` and explain why in the pull request.

## Copy

- No em dashes in docs or output. Plain words over cleverness.

## Before finishing

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
uv run evals -c examples/support_assistant/evals.yaml run --no-judge
```
