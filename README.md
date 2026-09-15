# Eval harness

Regression tests for LLM applications and AI agents, from
[Vantion Labs](https://vantion.co). Run it on every change to a prompt, model or
tool: it scores your test set with checks in code and a model grader, compares
the result with the last release, and fails the build when quality drops.

It reads test sets in the format of our
[eval test set template](https://github.com/vantionlabs/eval-test-set-template),
so a spreadsheet of cases your team already wrote becomes a CI gate.

## What you get

- **Test sets as files.** CSV or YAML in your repository, grouped by category and
  severity, reviewed like code.
- **Deterministic checks.** Required and forbidden content, citations that point
  at real sources, JSON schemas and expected tool calls, checked on every run.
- **Model-graded checks.** The six-criterion rubric from the template, with a
  pinned judge model and a versioned prompt. Pass rules are applied in code, and
  a calibration mode compares the judge with human labels.
- **A regression gate.** Pass rates per category are compared with a stored
  baseline. The build fails on a drop beyond the tolerance or on any new critical
  failure.
- **Cost and latency.** Tokens, cost and response time per case and per run, for
  the application and the judge, so a change that costs more shows up next to its
  quality result.
- **Reports.** A Markdown summary for pull requests and a JSON report per run to
  keep as history, or send to Langfuse.

## Quickstart

You need [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
uv run evals -c examples/support_assistant/evals.yaml run --no-judge
```

That runs 17 cases against an example support assistant and prints the summary:

```
## ✅ No regressions

| Category | Cases | Pass rate | Baseline | Critical failures | Cost | p50 | p95 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| adversarial | 2 | 100.0% | 100.0% | none | $0.0007 | 22ms | 22ms |
| escalation | 1 | 0.0% | 0.0% | none | $0.0004 | 21ms | 21ms |
...
```

One case fails, and the gate still passes: the failure is already in the baseline.
Break something, such as the refund policy in
`examples/support_assistant/kb/billing/refund-policy.md`, and run it again to see
the gate fail.

To grade the rubric cases too, set `ANTHROPIC_API_KEY` and drop `--no-judge`.

## Using it on your application

1. **Write the test set.** Start from the
   [template](https://github.com/vantionlabs/eval-test-set-template), or see
   [docs/test-sets.md](docs/test-sets.md) for every column.
2. **Write an adapter.** An async function that sends one case to your
   application and reports what came back:

   ```python
   from eval_harness.cases import Case
   from eval_harness.target import Response, Source, Usage


   async def answer(case: Case) -> Response:
       result = await my_app.ask(case.input)
       return Response(
           output=result.text,
           sources=[Source(id=doc.path, text=doc.text) for doc in result.documents],
           usage=[Usage(result.input_tokens, result.output_tokens, model=result.model)],
       )
   ```

   If your application already has an HTTP endpoint, use `target.http` instead.
3. **Configure it** in `evals.yaml`: test sets, the target, the judge, prices and
   the gate. The example's
   [`evals.yaml`](examples/support_assistant/evals.yaml) is commented.
4. **Make a baseline** from a run you are happy with: `evals baseline`.
5. **Add it to CI.** See [docs/ci.md](docs/ci.md).

## How a run works

```
test sets ──> runner ──> adapter ──> your application
                │
                ├─ deterministic checks ── failed? ──> case fails, judge skipped
                ├─ judge (rubric cases) ── pass rules in code
                │
                └─> report.json + report.md ──> gate vs baseline ──> exit 0 or 1
```

1. **Load.** Test sets and `evals.yaml` are read and validated before anything
   runs.
2. **Run.** Each case goes to your application through the adapter, with a
   concurrency limit, a timeout, and retries with backoff for rate limits and
   provider errors.
3. **Grade.** Deterministic checks run first. Cases that pass them and have a
   rubric go to the judge.
4. **Compare.** Pass rates, cost and latency are compared with the baseline, the
   reports are written, and the exit code tells CI whether to pass.

## Commands

| Command | What it does |
| --- | --- |
| `evals validate` | Load the config and test sets and count the cases, without running anything. |
| `evals run` | Run, write the reports, apply the gate. `--no-judge`, `--case ID`, `--category NAME`, `--baseline PATH`, `--no-gate`. |
| `evals gate REPORT` | Apply the gate to a saved report. |
| `evals baseline [REPORT]` | Make a report (by default the latest) the baseline. |
| `evals calibrate --labels FILE` | Compare the judge with human scores. See [docs/judge.md](docs/judge.md). |
| `evals export-langfuse REPORT` | Send a report to Langfuse. |

Every command takes `-c path/to/evals.yaml`. Exit codes: 0 when the gate passes, 1
when it fails, 2 when the config or a test set cannot be used.

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

## Licence

MIT. See [LICENSE](LICENSE). Built by [Vantion Labs](https://vantion.co); if you
want help putting evals around your own AI system,
[talk to the founder](https://vantion.co/book-a-call).
