"""The adapter between the harness and the application under test.

The harness calls `answer` once per case. Call your application the way it is
normally called, and report what it returned: the output, the sources it could
cite, the tools it called and the tokens it used.
"""

import asyncio

from assistant import SupportAssistant

from eval_harness.cases import Case
from eval_harness.target import Response, Source, Usage

assistant = SupportAssistant()


async def answer(case: Case) -> Response:
    reply = await asyncio.to_thread(assistant.answer, case.input)
    await asyncio.sleep(0.02)  # a stand-in for the time a real model call takes
    return Response(
        output=reply.text,
        sources=[Source(id=article.path, text=article.answer) for article in reply.sources],
        usage=[
            # A real target reports the model's token counts. These are made up.
            Usage(
                input_tokens=reply.words_in * 40,
                output_tokens=len(reply.text.split()) * 2,
                model="example-model",
            )
        ],
    )
