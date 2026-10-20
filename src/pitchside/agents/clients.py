"""Chat clients for the desk: Microsoft Foundry in production, scripted offline.

Models are passed to the desk as an ordered chain of (label, client): if a call to
one fails (timeout, quota, outage), the desk retries the same step on the next.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

import agent_framework as af
from pydantic import BaseModel

ModelChain = Sequence[tuple[str, Any]]

Reply = af.ChatResponse | Exception | Callable[[Sequence[af.Message]], af.ChatResponse]


class ScriptedChatClient(af.FunctionInvocationLayer, af.ChatMiddlewareLayer, af.BaseChatClient):
    """Plays back fixed replies in order; raises when the script runs out.

    Used by tests and by offline demos, so the desk runs without network access.
    `calls` keeps the messages of every request for assertions.
    """

    def __init__(self, replies: Sequence[Reply]) -> None:
        super().__init__()
        self.replies = list(replies)
        self.calls: list[list[af.Message]] = []

    def _inner_get_response(self, *, messages, stream, options, **kwargs):  # noqa: ANN001
        async def respond() -> af.ChatResponse:
            self.calls.append(list(messages))
            if not self.replies:
                raise RuntimeError("scripted model has no reply left (model unavailable)")
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply(messages) if callable(reply) else reply
        return respond()


def text_reply(text: str) -> af.ChatResponse:
    return af.ChatResponse(messages=[af.Message("assistant", [text])])


def tool_calls_reply(*calls: tuple[str, dict[str, Any]]) -> af.ChatResponse:
    contents = [af.Content.from_function_call(f"call_{i}", name, arguments=args)
                for i, (name, args) in enumerate(calls)]
    return af.ChatResponse(messages=[af.Message("assistant", contents)])


def json_reply(model: BaseModel) -> af.ChatResponse:
    return text_reply(model.model_dump_json())


def foundry_chain(credential: Any) -> list[tuple[str, Any]]:
    """Primary and optional fallback Foundry deployments, keyless (Entra ID).

    Reads FOUNDRY_PROJECT_ENDPOINT, AI_MODEL_DEPLOYMENT and AI_MODEL_FALLBACK_DEPLOYMENT
    from the environment (never from a .env file). Pass an async Azure credential
    and close it when done: locally `az login`, in Azure the managed identity, e.g.
    `async with azure.identity.aio.DefaultAzureCredential() as credential: ...`.
    """
    from agent_framework.foundry import FoundryChatClient

    endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    chain = [("primary", FoundryChatClient(project_endpoint=endpoint, credential=credential,
                                           model=os.environ["AI_MODEL_DEPLOYMENT"]))]
    fallback = os.environ.get("AI_MODEL_FALLBACK_DEPLOYMENT")
    if fallback:
        chain.append(("fallback", FoundryChatClient(project_endpoint=endpoint,
                                                    credential=credential, model=fallback)))
    return chain
