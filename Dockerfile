# The harness with both judge providers and the Langfuse export, for CI systems
# that run steps in containers. See docs/ci.md.
FROM python:3.12-slim

WORKDIR /opt/eval-harness
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[anthropic,openai,langfuse]"

WORKDIR /work
ENTRYPOINT ["evals"]
CMD ["--help"]
