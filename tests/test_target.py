import asyncio

import httpx
import pytest

from eval_harness.target import RetryableError, http_target, load_adapter
from tests.conftest import make_case


def test_http_target_sends_the_case_and_reads_a_response():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["authorization"], request.read()))
        return httpx.Response(
            200,
            json={
                "output": "Under our refund policy [1].",
                "sources": [{"id": "kb/billing/refund-policy.md", "text": "..."}],
                "tool_calls": [{"name": "search_kb", "arguments": {"q": "refund"}}],
                "usage": [{"input_tokens": 12, "output_tokens": 7, "model": "m"}],
            },
        )

    target = http_target(
        "http://app/eval",
        headers={"authorization": "Bearer t"},
        transport=httpx.MockTransport(handler),
    )

    response = asyncio.run(target(make_case(id="EVS-002")))

    assert response.output == "Under our refund policy [1]."
    assert response.sources[0].id == "kb/billing/refund-policy.md"
    assert response.tool_calls[0].arguments == {"q": "refund"}
    assert response.usage[0].output_tokens == 7
    assert seen[0][0] == "Bearer t" and b'"id":"EVS-002"' in seen[0][1]


@pytest.mark.parametrize("status", [429, 503])
def test_http_target_retries_rate_limits_and_server_errors(status: int):
    target = http_target(
        "http://app/eval", transport=httpx.MockTransport(lambda _: httpx.Response(status))
    )

    with pytest.raises(RetryableError):
        asyncio.run(target(make_case()))


def test_adapters_must_be_async_functions():
    with pytest.raises(ValueError, match="must look like"):
        load_adapter("no_colon")
    with pytest.raises(ValueError, match="must be an async function"):
        load_adapter("json:dumps")
