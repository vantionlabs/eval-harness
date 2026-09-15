"""The judges against each provider's real SDK, with the HTTP layer faked.

These check that the requests the SDKs build are the ones the harness means to
send, and that replies and errors are read correctly, without calling a model.
"""

import asyncio
import json

import anthropic
import httpx2
import openai
import pytest

from eval_harness.judge import AnthropicJudge, OpenAIJudge
from eval_harness.target import RetryableError

VERDICT = json.dumps({"scores": {"correctness": "2"}, "reasons": {}})


def transport(handler):
    """Both SDKs are built on httpx2, so the fake transport is httpx2's."""
    requests: list[dict] = []

    def record(request):
        requests.append(json.loads(request.content))
        return handler(request)

    return httpx2.MockTransport(record), requests


def test_anthropic_judge_asks_for_structured_output_and_reads_usage():
    mock, requests = transport(
        lambda _: httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": VERDICT}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 812, "output_tokens": 64},
            },
        ),
    )
    client = anthropic.AsyncAnthropic(
        api_key="test", http_client=httpx2.AsyncClient(transport=mock)
    )

    reply = asyncio.run(AnthropicJudge("claude-sonnet-5", client=client).score("grade this"))

    assert reply.text == VERDICT
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (812, 64)
    assert reply.usage.model == "anthropic:claude-sonnet-5"
    body = requests[0]
    assert body["model"] == "claude-sonnet-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["messages"] == [{"role": "user", "content": "grade this"}]


def test_anthropic_rate_limits_are_retryable():
    error = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    mock, _ = transport(lambda _: httpx2.Response(429, json=error))
    client = anthropic.AsyncAnthropic(
        api_key="test", http_client=httpx2.AsyncClient(transport=mock), max_retries=0
    )

    with pytest.raises(RetryableError):
        asyncio.run(AnthropicJudge("claude-sonnet-5", client=client).score("grade this"))


def test_openai_judge_uses_a_strict_json_schema_and_reads_usage():
    mock, requests = transport(
        lambda _: httpx2.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": VERDICT, "annotations": []}],
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "usage": {
                    "input_tokens": 900,
                    "output_tokens": 70,
                    "total_tokens": 970,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )
    )
    client = openai.AsyncOpenAI(api_key="test", http_client=httpx2.AsyncClient(transport=mock))

    reply = asyncio.run(OpenAIJudge("gpt-5", client=client).score("grade this"))

    assert reply.text == VERDICT and reply.usage.input_tokens == 900
    text_format = requests[0]["text"]["format"]
    assert text_format["type"] == "json_schema" and text_format["strict"] is True
