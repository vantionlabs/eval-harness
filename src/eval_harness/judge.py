"""The model that scores rubric cases.

A judge is named `provider:model`, such as `anthropic:claude-sonnet-5` or
`openai:gpt-5`. Pin an exact model version: a judge that silently changes
model is a judge whose scores you can no longer compare with last month's.

Both providers are asked for structured output against `rubric.OUTPUT_SCHEMA`,
so a well-behaved judge cannot return a shape the parser does not expect.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from eval_harness.rubric import OUTPUT_SCHEMA
from eval_harness.target import RetryableError, Usage

SYSTEM = "You are a careful evaluator. Answer only with the requested JSON."


@dataclass(frozen=True)
class JudgeReply:
    text: str
    usage: Usage


class Judge(Protocol):
    model: str
    """`provider:model`, recorded in every report."""

    async def score(self, prompt: str) -> JudgeReply: ...


class AnthropicJudge:
    def __init__(self, model: str, *, max_tokens: int = 2000, client: Any = None) -> None:
        try:
            import anthropic
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "install the anthropic extra: uv add 'eval-harness[anthropic]'"
            ) from error
        self._anthropic = anthropic
        self._client = client or anthropic.AsyncAnthropic()
        self._model = model
        self.model = f"anthropic:{model}"
        self._max_tokens = max_tokens

    async def score(self, prompt: str) -> JudgeReply:
        errors = self._anthropic
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            )
        except (errors.RateLimitError, errors.APIConnectionError, errors.InternalServerError) as e:
            raise RetryableError(str(e)) from e
        except errors.APIStatusError as error:
            if error.status_code in (408, 409, 429) or error.status_code >= 500:
                raise RetryableError(str(error)) from error
            raise
        text = "".join(block.text for block in message.content if block.type == "text")
        usage = Usage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            model=self.model,
        )
        return JudgeReply(text=text, usage=usage)


class OpenAIJudge:
    def __init__(self, model: str, *, max_tokens: int = 2000, client: Any = None) -> None:
        try:
            import openai
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise RuntimeError("install the openai extra: uv add 'eval-harness[openai]'") from error
        self._openai = openai
        self._client = client or openai.AsyncOpenAI()
        self._model = model
        self.model = f"openai:{model}"
        self._max_tokens = max_tokens

    async def score(self, prompt: str) -> JudgeReply:
        errors = self._openai
        text_format: Any = {
            "format": {
                "type": "json_schema",
                "name": "rubric_scores",
                "schema": OUTPUT_SCHEMA,
                "strict": True,
            }
        }
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=SYSTEM,
                input=prompt,
                max_output_tokens=self._max_tokens,
                text=text_format,
            )
        except (errors.RateLimitError, errors.APIConnectionError, errors.InternalServerError) as e:
            raise RetryableError(str(e)) from e
        usage = response.usage
        return JudgeReply(
            text=response.output_text,
            usage=Usage(
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                model=self.model,
            ),
        )


def make_judge(spec: str) -> Judge:
    provider, _, model = spec.partition(":")
    if not model:
        raise ValueError(f"judge model must look like `provider:model`, got {spec!r}")
    if provider == "anthropic":
        return AnthropicJudge(model)
    if provider == "openai":
        return OpenAIJudge(model)
    raise ValueError(f"unknown judge provider {provider!r}; use anthropic or openai")
