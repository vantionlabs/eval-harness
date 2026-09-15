"""The system under test, and how the runner talks to it.

A target is an async function that takes a `Case` and returns a `Response`:

    async def answer(case: Case) -> Response: ...

Point `target.adapter` in the config at it as `module.path:function`. The
function calls your application however it is normally called (a function, an
HTTP endpoint, an agent loop) and reports what came back. The built-in HTTP
target covers applications that already expose an endpoint.
"""

import importlib
import inspect
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

import httpx

from eval_harness.cases import Case


class RetryableError(Exception):
    """A failure worth retrying: a rate limit, an overloaded provider, a dropped connection."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    """Used to price the tokens. Leave unset if `cost_usd` is already known."""
    cost_usd: float | None = None
    """Set when the application computes its own cost, which then takes precedence."""


@dataclass(frozen=True)
class Source:
    """A passage the answer could cite. `[1]` in the output refers to the first source."""

    id: str
    text: str = ""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    output: str
    sources: list[Source] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)
    """One entry per model call the target made."""
    metadata: dict[str, Any] = field(default_factory=dict)


Target = Callable[[Case], Coroutine[Any, Any, Response]]


def load_adapter(spec: str) -> Target:
    """Import `module.path:function`."""
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise ValueError(f"adapter must look like `module.path:function`, got {spec!r}")
    target = getattr(importlib.import_module(module_name), attribute, None)
    if target is None or not inspect.iscoroutinefunction(target):
        raise ValueError(f"{spec} must be an async function taking a Case and returning a Response")
    return target


def http_target(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 60.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Target:
    """POST each case as JSON and read a `Response`-shaped JSON body back.

    Request:  {"id", "input", "category", "context_ref"}
    Response: {"output", "sources"?: [{"id","text"}], "tool_calls"?: [{"name","arguments"}],
               "usage"?: [{"input_tokens","output_tokens","model","cost_usd"}], "metadata"?}
    """

    async def call(case: Case) -> Response:
        async with httpx.AsyncClient(
            timeout=timeout_seconds, headers=headers, transport=transport
        ) as client:
            try:
                reply = await client.post(
                    url,
                    json={
                        "id": case.id,
                        "input": case.input,
                        "category": case.category,
                        "context_ref": list(case.context_ref),
                    },
                )
            except httpx.TransportError as error:
                raise RetryableError(f"could not reach {url}: {error}") from error
        if reply.status_code == 429 or reply.status_code >= 500:
            raise RetryableError(f"{url} answered {reply.status_code}")
        reply.raise_for_status()
        return response_from_json(reply.json())

    return call


def response_from_json(body: dict[str, Any]) -> Response:
    return Response(
        output=str(body.get("output", "")),
        sources=[
            Source(id=str(s["id"]), text=str(s.get("text", ""))) for s in body.get("sources", [])
        ],
        tool_calls=[
            ToolCall(name=str(t["name"]), arguments=dict(t.get("arguments") or {}))
            for t in body.get("tool_calls", [])
        ],
        usage=[
            Usage(
                input_tokens=int(u.get("input_tokens", 0)),
                output_tokens=int(u.get("output_tokens", 0)),
                model=u.get("model"),
                cost_usd=u.get("cost_usd"),
            )
            for u in body.get("usage", [])
        ],
        metadata=dict(body.get("metadata") or {}),
    )
