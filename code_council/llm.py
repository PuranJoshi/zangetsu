"""LLM wrapper (OpenAI-compatible).

All provider-specific access lives here. The rest of the codebase calls
complete(prompt, ...) and never talks to the API directly.

Uses the OpenAI Python SDK as a protocol-compatible client pointed at any
OpenAI-compatible base URL. Works with OpenAI, Azure OpenAI, Ollama,
LM Studio, Groq, Together AI, or any other OpenAI-compatible endpoint.

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

    Supports addition (``usage_a + usage_b``) for easy aggregation
    across multiple LLM calls within a pipeline stage.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Accumulate token counts: ``usage_a + usage_b``."""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        """In-place addition: ``usage += other_usage``."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        return self

    def to_dict(self) -> dict[str, int]:
        """Serialize to a plain dict for JSON storage / SSE events."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


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
# Token tracker (per-stage accumulator)
# ---------------------------------------------------------------------------


class TokenTracker:
    """Accumulates token usage per pipeline stage and overall total.

    Usage::

        tracker = TokenTracker()
        tracker.record("framing", usage_from_framer)
        tracker.record("advisors", usage_from_advisors)
        print(tracker.format_stage_line("framing"))  # inline display
        print(tracker.format_summary())               # final table

    Each call to ``record()`` either creates a new stage entry or adds
    to an existing one.  The ``total`` is updated on every call.
    """

    def __init__(self) -> None:
        self.stage_usage: dict[str, TokenUsage] = {}
        self.total: TokenUsage = TokenUsage()

    def record(self, stage: str, usage: TokenUsage) -> None:
        """Add token usage for a pipeline stage."""
        if stage in self.stage_usage:
            self.stage_usage[stage] += usage
        else:
            self.stage_usage[stage] = TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
        self.total += usage

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage."""
        return {
            "stages": {name: u.to_dict() for name, u in self.stage_usage.items()},
            "total": self.total.to_dict(),
        }

    def format_stage_line(self, stage: str) -> str:
        """One-liner for display after a stage completes."""
        usage = self.stage_usage.get(stage, TokenUsage())
        return (
            f"  {stage.title()}: {usage.total_tokens:,} tokens "
            f"({usage.prompt_tokens:,} in + {usage.completion_tokens:,} out) "
            f"| Total: {self.total.total_tokens:,}"
        )

    def format_summary(self) -> str:
        """Full summary table for display at the end of the pipeline."""
        sep = "=" * 60
        lines = [f"\n{sep}", " TOKEN USAGE", sep]
        for name, usage in self.stage_usage.items():
            lines.append(
                f"  {name.title():<14} {usage.total_tokens:>6,} tokens "
                f"({usage.prompt_tokens:,} in + {usage.completion_tokens:,} out)"
            )
        lines.append("  " + "\u2500" * 44)
        lines.append(
            f"  {'Total':<14} {self.total.total_tokens:>6,} tokens "
            f"({self.total.prompt_tokens:,} in + {self.total.completion_tokens:,} out)"
        )
        lines.append(sep)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Minimal async LLM interface used throughout code-council.

    This is the same Protocol defined in advisors.py. Having it here
    too is intentional -- each module is independently importable.
    The Protocol is so small that duplication is cleaner than a shared
    module just for a type.
    """

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> str: ...

    async def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> str: ...

    async def complete_with_usage(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult: ...

    async def chat_with_usage(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult: ...


# ---------------------------------------------------------------------------
# Real implementation backed by any OpenAI-compatible API
# ---------------------------------------------------------------------------


class OpenAICompatibleLLM:
    """Async LLM client that talks to any OpenAI-compatible endpoint.

    This is the ONLY class that knows about the API. Everything else
    depends on the LLMClient Protocol, not this concrete class.
    Swapping providers = changing the base URL and API key.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._settings.require_llm_credentials()
        self._client = AsyncOpenAI(
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url,
        )

    async def _call_api(
        self,
        messages: list[Message],
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult:
        """Low-level API call with retry logic.

        Returns an LLMResult containing the response text and token usage.

        Args:
            model: Optional model override. If provided (non-empty string),
                uses this model instead of the global default from settings.
                This enables per-advisor model routing.

        Python lesson: asyncio.wait_for()
            Wraps a coroutine with a timeout. If the API call takes
            longer than `timeout` seconds, it raises asyncio.TimeoutError.
            Without this, a hung API call would block forever.
        """
        timeout = timeout or float(self._settings.code_council_agent_timeout_seconds)

        # Use the per-call model override if provided, else global default.
        effective_model = model if model else self._settings.code_council_model

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
                        model=effective_model,
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
        model: str | None = None,
    ) -> str:
        """Send a single prompt and return the assistant text."""
        result = await self._call_api(
            [{"role": "user", "content": prompt}],
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
            model=model,
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
        model: str | None = None,
    ) -> str:
        """Send a multi-turn conversation and return the assistant reply."""
        result = await self._call_api(
            messages,
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
            model=model,
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
        model: str | None = None,
    ) -> LLMResult:
        """Like complete() but returns an LLMResult with token usage."""
        return await self._call_api(
            [{"role": "user", "content": prompt}],
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
            model=model,
        )

    async def chat_with_usage(
        self,
        messages: list[Message],
        *,
        max_retries: int = 3,
        timeout: float | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> LLMResult:
        """Like chat() but returns an LLMResult with token usage."""
        return await self._call_api(
            messages,
            max_retries=max_retries,
            timeout=timeout,
            temperature=temperature,
            seed=seed,
            model=model,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm(settings: Settings | None = None) -> OpenAICompatibleLLM:
    """Create an OpenAICompatibleLLM using the given (or default) settings.

    Why a factory function?
        Same reason as get_settings() -- tests can pass custom settings
        with different API keys/URLs. Production code calls get_llm()
        with no args and gets the real client.
    """
    return OpenAICompatibleLLM(settings)
