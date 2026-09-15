# Contributing

Thanks for helping. The bar for a change is: does it make results more
trustworthy or easier to act on, without making a test set harder to write?

## Good contributions

- Bug fixes, especially anywhere a result could claim more than was checked.
- New deterministic checks that many applications need, as optional columns.
- Judge providers that support structured output.
- Docs that were wrong or missing when you set the harness up.

Open an issue before starting something larger, such as a new report format or a
different gating model, so we can agree it belongs here.

## Making a change

1. Read [AGENTS.md](AGENTS.md). Its rules apply to human and agent changes alike.
2. Run the checks:

   ```bash
   uv sync --all-extras
   uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
   uv run evals -c examples/support_assistant/evals.yaml run --no-judge
   ```

3. Keep pull requests to one change, and say why in the description.

## Security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).
