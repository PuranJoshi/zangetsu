"""Langdock LLM wrapper.

All provider-specific access lives here. The rest of the codebase calls
complete(prompt, ...) and never talks to the API directly.

Uses the OpenAI Python SDK as a protocol-compatible client pointed at the
Langdock base URL. Swapping the provider later means changing this file only.

Python lesson: AsyncOpenAI
    The openai library provides both sync (OpenAI) and async (AsyncOpenAI)
    clients. We use async because our advisors run in parallel via
    asyncio.gather(). If we used the sync client, each advisor would
    block the others -- total time = sum of all calls instead of max.

Python lesson: retry with exponential backoff
    Network calls fail. The retry logic below tries 3 times with
    increasing wait times: 2s, 4s, 8s (2^attempt). This handles
    transient failures (rate limits, network blips) without manual
    intervention. The `last_exc` pattern preserves the original error
    for the final RuntimeError.

Python lesson: dataclass vs Pydantic (again)
    TokenUsage and LLMResult are @dataclass, not BaseModel.
    They're internal data flowing between functions, never serialized
    to JSON or validated from external input. Dataclasses are simpler
    and faster for this use case.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI

from code_council.config import Settings, get_settings

logger = logging.getLogger(__name__)


# Type alias for chat messages. Each message is a dict with "role" and "content".
# role is one of: "system", "user", "assistant"
Message = dict[str, str]


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts from a single LLM call.

    Why track this? LLM calls cost money. By recording token usage per
    call, we can show the user how much each plan costs and optimize
    prompts that are too expensive.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResult:
    """Text response plus token usage metadata from an LLM call.

    Python lesson: field(default_factory=...)
        For mutable defaults in dataclasses, you must use default_factory.
        Writing `usage: TokenUsage = TokenUsage()` would share ONE instance
        across all LLMResult objects (the shared mutable default bug).
        default_factory=TokenUsage calls TokenUsage() fresh for each instance.
    """

    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Minimal async LLM interface used throughout code-council.

    This is the same Protocol defined in advisors.py. Having it here
    too is intentional -- each module is independently importable.
    The Protocol is so small (2 methods) that duplication is cleaner
    than a shared module just for a type.
    """

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str: ...

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Real implementation backed by Langdock / OpenAI-compatible API
# ---------------------------------------------------------------------------


class LangdockLLM:
    """Async LLM client that talks to a Langdock OpenAI-compatible endpoint.

    This is the ONLY class that knows about the API. Everything else
    depends on the LLMClient Protocol, not this concrete class.
    Swapping providers = rewriting this class, nothing else changes.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._settings.require_langdock()
        self._client = AsyncOpenAI(
            api_key=self._settings.langdock_api_key,
            base_url=self._settings.langdock_base_url,
        )

    async def _call_api(
        self,
        messages: list[Message],
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        """Low-level API call with retry logic.

        Returns an LLMResult containing the response text and token usage.

        Python lesson: asyncio.wait_for()
            Wraps a coroutine with a timeout. If the API call takes
            longer than `timeout` seconds, it raises asyncio.TimeoutError.
            Without this, a hung API call would block forever.
        """
        timeout = timeout or float(self._settings.code_council_agent_timeout_seconds)

        extra_kwargs: dict[str, Any] = {}
        if temperature is not None:
            extra_kwargs["temperature"] = temperature
        if seed is not None:
            extra_kwargs["seed"] = seed

        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self._settings.code_council_model,
                        messages=messages,  # type: ignore[arg-type]
                        **extra_kwargs,
                    ),
                    timeout=timeout,
                )
                text = (response.choices[0].message.content or "").strip()
                usage = TokenUsage()
                if response.usage:
                    usage = TokenUsage(
                        prompt_tokens=response.usage.prompt_tokens or 0,
                        completion_tokens=response.usage.completion_tokens or 0,
                        total_tokens=response.usage.total_tokens or 0,
                    )
                return LLMResult(text=text, usage=usage)
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "LLM call attempt %d/%d failed (%s), retrying in %ds",
                        attempt,
                        max_retries,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)

        raise RuntimeError(f"LLM call failed after {max_retries} attempts") from last_exc

    # -- Public API (backward-compatible: returns str) ---------------------

    async def complete(
        self,
        prompt: str,
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str:
        """Send a single prompt and return the assistant text."""
        result = await self._call_api(
            [{"role": "user", "content": prompt}],
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
        )
        return result.text

    async def chat(
        self,
        messages: list[Message],
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str:
        """Send a multi-turn conversation and return the assistant reply."""
        result = await self._call_api(
            messages,
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
        )
        return result.text

    # -- Extended API (returns text + token usage) -------------------------

    async def complete_with_usage(
        self,
        prompt: str,
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        """Like complete() but returns an LLMResult with token usage."""
        return await self._call_api(
            [{"role": "user", "content": prompt}],
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
        )

    async def chat_with_usage(
        self,
        messages: list[Message],
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        """Like chat() but returns an LLMResult with token usage."""
        return await self._call_api(
            messages,
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm(settings: Settings | None = None) -> LangdockLLM:
    """Create a LangdockLLM using the given (or default) settings.

    Why a factory function?
        Same reason as get_settings() -- tests can pass custom settings
        with different API keys/URLs. Production code calls get_llm()
        with no args and gets the real client.
    """
    return LangdockLLM(settings)
