# Running in CI

## GitHub Actions

```yaml
name: Evals

on:
  pull_request:
    paths: ["prompts/**", "app/**", "evals/**"]

jobs:
  evals:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.1.0
      - run: uv sync --all-extras
      - name: Run evals
        run: uv run evals -c evals/evals.yaml run
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - name: Keep the report
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: eval-report
          path: evals/reports/
```

`evals run` exits 1 when the gate fails, which fails the job. When
`GITHUB_STEP_SUMMARY` is set, as it is on GitHub Actions, the Markdown summary is
added to the job summary, so the pass rates and failures show on the run without
opening a log.

Each run also writes `reports/latest.md`. To post the summary as a pull request
comment, add a step that posts that file with the action or bot you already use.

## When to run what

- **On pull requests that touch prompts, models, tools or retrieval**: the full
  run with the judge. This is the gate.
- **On every pull request**, if the full run is slow or costly: `--no-judge`, with a
  baseline made without a judge. Deterministic checks are fast and free.
- **Nightly**: the full run against the main branch, to catch drift in a provider's
  model behind the same version name.

A run with the judge and a baseline without one cannot be compared; the gate says
so. Keep one baseline per mode if you run both.

## Keeping the baseline

The baseline is a report from a run you accept, committed to the repository:

```bash
uv run evals -c evals/evals.yaml run
uv run evals -c evals/evals.yaml baseline   # copies reports/latest.json to gate.baseline
git add evals/baseline.json
```

Update it when a change is meant to shift results: a new release, a better prompt,
new cases. Review the diff of `baseline.json` in the pull request like any other
change, because updating the baseline is how a regression would be waved through.

## Tolerance

`gate.tolerance` is how far a category's pass rate may drop before the gate fails.
The default is 2 percentage points. A category with 5 cases moves 20 points per
case, so small categories effectively allow no drop at all. That is intended:
look at the failure rather than raising the tolerance.

## Langfuse

To keep run history in Langfuse next to production traces:

```bash
uv run evals export-langfuse evals/reports/latest.json
```

with `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` set. Each
case becomes a trace in one session per run, scored with `eval_passed` and one
score per rubric criterion.

## Docker

The `Dockerfile` builds an image with the harness and both judge providers, for CI
systems that run steps in containers. Mount your project and point `-c` at its
config:

```bash
docker build -t eval-harness .
docker run --rm -v "$PWD:/work" -w /work -e ANTHROPIC_API_KEY eval-harness -c evals/evals.yaml run
```

An adapter that imports your application needs the application's dependencies in
the image too; extend the image, or use `target.http` against a running instance.
