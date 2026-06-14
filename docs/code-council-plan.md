# Code Council: Implementation Plan

> A standalone MCP server that plans code changes through multi-advisor
> deliberation, then negotiates feasibility with AI coding tools before
> handing off for execution.

**Version:** 0.1.0 (initial build)
**Parent project:** council-me (patterns borrowed, code independent)
**Target AI tools:** GitHub Copilot, Cursor, OpenCode (any MCP-compatible tool)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack and Project Structure](#3-tech-stack-and-project-structure)
4. [Module: config.py](#4-module-configpy)
5. [Module: llm.py](#5-module-llmpy)
6. [Module: context.py](#6-module-contextpy)
7. [Module: advisors.py](#7-module-advisorspy)
8. [Module: synthesizer.py](#8-module-synthesizerpy)
9. [Module: state.py and storage.py](#9-module-statepy-and-storagepy)
10. [Module: mcp_server.py](#10-module-mcp_serverpy)
11. [Module: negotiation.py](#11-module-negotiationpy)
12. [Module: cli.py](#12-module-clipy)
13. [Skill Files](#13-skill-files)
14. [Testing Strategy](#14-testing-strategy)
15. [AI Tool Configuration and Build Order](#15-ai-tool-configuration-and-build-order)

---

## 1. Overview

### What is Code Council?

Code Council is a planning layer that sits between you and your AI coding
tool. Instead of going straight from "I want to add authentication" to
"the AI is writing code," Code Council inserts a structured deliberation
phase with a requirements gate:

1. **You describe a feature request** via the `bankai` command.
2. **The Framer** (product/business lens) defines structured requirements --
   epic, stories, tasks, or bug -- in Jira-style format. It asks clarifying
   questions until ambiguity is resolved. **No advisor runs until requirements
   are clear.**
3. **5 technical advisors** analyze the framed requirements from different
   angles (architecture, security, quality, risk, execution) -- in parallel.
4. **A synthesizer** produces a structured implementation plan.
5. **The AI coding tool reviews** the plan for feasibility.
6. **If infeasible**, the council reassesses with the AI tool's feedback.
7. **Once agreed**, the plan becomes a step-by-step prompt the AI tool executes.

### Why?

AI coding tools are good at writing code but bad at two things: understanding
what to build, and planning how to build it. They jump straight into
implementation without clarifying requirements, thinking through architecture,
security, test impact, or sequencing. Code Council forces **requirements
definition first** (what and why), then **structured planning** (how), using
multiple analytical lenses, before a single line of code is written.

### How does it connect to AI tools?

Via **MCP (Model Context Protocol)**. Code Council runs as an MCP server.
Cursor, GitHub Copilot (VS Code), and OpenCode all support MCP natively.
The AI tool calls Code Council's tools during its workflow -- no clipboard,
no copy-pasting.

### Relationship to council-me

Code Council is a **separate standalone project**. It borrows architectural
patterns from council-me (the LLM client abstraction, config via
pydantic-settings, FakeLLM testing, JSON transcript storage) but shares
no code. The codebases are fully independent.

---

## 2. Architecture

### System Flow

```
User describes feature request
       |
       v
+------------------+
| bankai command   |  <-- AI tool calls bankai() via MCP
+------------------+
       |
       v
+------------------+
| Context Gatherer |  Reads target project filesystem directly:
|   (context.py)   |  directory tree, config files, tech stack,
+------------------+  relevant source files, test patterns
       |
       v
+===========================+
| PHASE 1: FRAMING          |  Requirements gate -- nothing
|                           |  proceeds until this is clear
| +---------------------+  |
| | Framer              |  |  Defines: epic / story / task / bug
| | (framer.py)         |  |  Asks clarifying questions
| |                     |  |  Produces FramedRequirement (Jira-style)
| +---------------------+  |
|           |               |
|           v               |
|   Requirements clear? -+  |
|   |                  |    |
|   v NO               v YES|
|   Ask user for       |    |
|   clarification      |    |
|   (loop until clear) |    |
+===========================+
       |
       v
+===========================+
| PHASE 2: ADVISING         |  Technical deliberation on
|                           |  the framed requirements
| +-------------------------+
| | 5 Technical Advisors    |  Each gets: framed requirements +
| |         (parallel)      |  project context + their skill prompt
| |                         |
| | - Architect Advisor     |  All run via asyncio.gather()
| | - Security Advisor      |  Each has distinct temperature/seed
| | - Quality Advisor       |  Skills auto-discovered from .md files
| | - Risk Advisor          |
| | - Executor Advisor      |
| +-------------------------+
+===========================+
       |
       v
+------------------+
| Synthesizer      |  Receives framed requirements +
|                  |  all 5 advisor analyses.
|                  |  Produces a structured ChangePlan:
|                  |  affected files, implementation steps,
|                  |  sequencing, risks, acceptance criteria.
+------------------+
       |
       v
+------------------+         +--------------------+
| Plan State:      | ------> | MCP Server exposes |
| PROPOSED         |         | plan to AI tool    |
+------------------+         +--------------------+
       |                              |
       v                              v
+------------------+         +--------------------+
| AI tool calls    | <------ | AI tool reviews    |
| review_plan()    |         | plan with its own  |
|                  |         | project knowledge  |
+------------------+         +--------------------+
       |
       +--- feasible? ---+
       |                  |
       v NO               v YES
+------------------+  +------------------+
| Re-run advisors  |  | Plan State:      |
| with AI tool's   |  | AGREED           |
| feedback injected|  +------------------+
| (max 3 rounds)   |         |
+------------------+         v
       |              +------------------+
       +------------> | AI tool calls    |
                      | execute_plan()   |
                      | Gets step-by-step|
                      | coding prompt    |
                      +------------------+
```

### Key Design Principles

1. **MCP-native.** The primary interface is MCP tools. AI tools call Code
   Council directly via tool calls. No clipboard, no file sharing.

2. **STDIO transport.** All three target AI tools (Copilot, Cursor, OpenCode)
   support STDIO-based MCP servers. Simpler than HTTP, works locally.

3. **Direct filesystem for context.** Code Council reads the target project's
   files directly. It runs locally, so there is no need to ask the AI tool
   to relay file contents via MCP.

4. **Async throughout.** All LLM calls use `asyncio`. The 5 technical
   advisors run concurrently via `asyncio.gather()`. The Framer runs
   sequentially before them (it must complete before advisors start).

5. **Requirements gate.** The Framer must produce a clear, unambiguous
   `FramedRequirement` before any technical advisor runs. If the feature
   request is vague, the Framer asks clarifying questions via the AI tool
   (which relays them to the user). This prevents the council from
   deliberating on poorly defined work.

6. **Protocol-based LLM abstraction.** A Python `Protocol` class defines
   the LLM interface. The real implementation talks to Langdock. Tests
   supply a `FakeLLM`. Swapping providers means changing one file.

7. **Stateful plans.** Each plan has a lifecycle: `framing -> drafting ->
   proposed -> reviewing -> agreed -> executing -> completed`. The state
   machine prevents advisors from running on unframed requests, and
   prevents executing a plan that hasn't been reviewed.

8. **Configurable negotiation depth.** Default max 3 rounds of back-and-forth
   between the council and AI tool. If they can't agree, surface to the
   human with both positions.

9. **Tool-agnostic by design.** The MCP server doesn't know which AI tool is
   calling it. Any MCP-compatible tool works. Adding support for a new tool
   means adding one JSON config block on the tool's side -- zero code changes
   in Code Council.

10. **Token usage tracking.** Every LLM call returns `TokenUsage` (prompt,
    completion, total token counts) via the `LLMResult` dataclass. The
    `complete_with_usage()` / `chat_with_usage()` methods expose this.
    Advisors and the synthesizer should use these to track per-plan token
    cost. This follows the pattern introduced in council-me 0.10.0.

11. **Conditional expensive work.** council-me 0.10.0 introduced a
    `_safety_relevant()` heuristic that skips the safety steward when the
    question doesn't touch sensitive domains (saves 1 LLM call). Code
    Council should adopt the same pattern: if the Security advisor detects
    no security-relevant content via a fast keyword heuristic, it can
    return a brief "no concerns" response without a full LLM call. This
    is a v2 optimization -- for v1, always run all 5 technical advisors.

12. **Extensible skill registry.** All roles (advisors, framer, synthesizer)
    are defined by self-describing Markdown files with YAML frontmatter in
    the `skills/` directory. Adding a new advisor means dropping a `.md`
    file -- no Python code changes. Disabling one means setting
    `enabled: false` in frontmatter. This makes the council composable
    and evolve-friendly.

### LLM Call Budget

| Scenario | Framer | Advisor calls | Synthesizer | Total |
|---|---|---|---|---|
| First pass (no clarification) | 1 | 5 | 1 | **7** |
| First pass (1 clarification round) | 2 | 5 | 1 | **8** |
| Each negotiation round | 0 | 5 | 1 | **6** |
| Typical (1 clarification + 1 negotiation) | 2 | 10 | 2 | **14** |
| Maximum (3 clarifications + 3 negotiations) | 4 | 20 | 4 | **28** |

---

## 3. Tech Stack and Project Structure

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| `python` | >=3.11 | Runtime |
| `mcp[cli]` | >=1.2.0 | MCP Python SDK (FastMCP server) |
| `openai` | >=1.30.0 | AsyncOpenAI client for Langdock |
| `typer` | >=0.12.0 | CLI framework |
| `pydantic` | >=2.7.0 | Data models (ChangePlan, ProjectContext, etc.) |
| `pydantic-settings` | >=2.3.0 | Settings from environment variables |
| `pyyaml` | >=6.0 | YAML frontmatter parsing for skill files |
| `httpx` | >=0.27.0 | HTTP client (future use, health checks) |

Dev dependencies:

| Package | Version | Purpose |
|---|---|---|
| `pytest` | >=8.0.0 | Test runner |
| `pytest-asyncio` | >=0.23.0 | Async test support |
| `ruff` | >=0.4.0 | Linting |

### Directory Structure

Create this project as a **sibling directory** to council-me, not inside it:

```
code-council/                        # NEW PROJECT ROOT
  pyproject.toml                     # Build config, deps, scripts
  README.md                         # Project overview
  AGENTS.md                         # Tool-agnostic AI agent instructions

  code_council/                      # Main Python package
    __init__.py                      # Version = "0.1.0"
    config.py                        # Settings (env vars, Langdock, paths)
    llm.py                           # AsyncOpenAI wrapper via Langdock
    context.py                       # Project filesystem scanner
    advisors.py                      # Advisor registry + parallel execution
    synthesizer.py                   # Plan synthesis from advisor outputs
    state.py                         # Plan state machine
    storage.py                       # JSON plan persistence
    negotiation.py                   # Feasibility negotiation loop
    mcp_server.py                    # FastMCP server (tools + resources)
    cli.py                           # Typer CLI entry point

    skills/                          # Self-describing skill files (YAML frontmatter)
      architect.md                   # Architecture advisor skill
      security.md                    # Security advisor skill
      quality.md                     # Quality/DX advisor skill
      risk.md                        # Risk advisor skill
      executor.md                    # Executor advisor skill
      business.md                    # Business & Impact advisor skill
      synthesizer.md                 # Plan synthesis skill

  tests/
    __init__.py
    conftest.py                      # Shared fixtures (FakeLLM, fake_context)
    test_config.py                   # Settings, env loading
    test_context.py                  # Filesystem scanning, tech detection
    test_advisors.py                 # Advisor registry, execution, diversity
    test_synthesizer.py              # Plan synthesis, output structure
    test_state.py                    # State machine transitions
    test_storage.py                  # Plan persistence
    test_negotiation.py              # Feedback loop, max rounds
    test_mcp_server.py              # MCP tool calls end-to-end
```

### pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "code-council"
version = "0.1.0"
description = "MCP server that plans code changes through multi-advisor deliberation"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "mcp[cli]>=1.2.0",
    "openai>=1.30.0",
    "typer>=0.12.0",
    "httpx>=0.27.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.0",
]

[project.scripts]
code-council = "code_council.cli:app"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "W"]
```

### `__init__.py`

```python
"""Code Council -- MCP server for AI-assisted code change planning."""

__version__ = "0.1.0"
```

---

## 4. Module: config.py

**File:** `code_council/config.py`

This module handles all configuration. It follows the same pattern as
council-me's `config.py`: a simple env file loader that runs before pydantic,
then a `BaseSettings` class that reads environment variables.

### Environment File

Settings are loaded from `~/.code-council/env`. The file uses `KEY=VALUE`
format. Existing environment variables take precedence (never overwritten).

### Settings Class

```python
"""Configuration for code-council.

Loads settings from environment variables and optionally from ~/.code-council/env.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

_ENV_FILE = Path.home() / ".code-council" / "env"


def _load_env_file(path: Path = _ENV_FILE) -> None:
    """Read a simple KEY=VALUE env file and inject into os.environ.

    Lines starting with # and blank lines are ignored.
    Existing environment variables take precedence.
    """
    if not path.is_file():
        return
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_file()


class Settings(BaseSettings):
    """Central configuration -- all values come from environment variables."""

    # -- Langdock / LLM --
    langdock_api_key: str = Field(
        default="",
        description="API key for the Langdock-compatible endpoint.",
    )
    langdock_base_url: str = Field(
        default="",
        description="Base URL of the Langdock OpenAI-compatible API.",
    )
    code_council_model: str = Field(
        default="REPLACE_ME_WITH_YOUR_MODEL",
        description="Model identifier passed to the LLM provider.",
    )

    # -- Agent behaviour --
    code_council_agent_timeout_seconds: int = Field(default=120)
    code_council_advisor_temperature_spread: float = Field(
        default=0.4,
        description=(
            "Range of temperature variation across the 5 advisors. "
            "Advisors are assigned temperatures from "
            "(1.0 - spread) to 1.0 based on their role."
        ),
    )

    # -- Negotiation --
    code_council_max_negotiation_rounds: int = Field(
        default=3,
        description="Maximum rounds of plan negotiation with the AI tool.",
    )

    # -- Plans storage --
    code_council_save_plans: bool = Field(default=True)
    code_council_plan_dir: str = Field(
        default=str(Path.home() / ".code-council" / "plans"),
    )

    model_config = {"env_prefix": "", "case_sensitive": False}

    # -- Helpers --

    def require_langdock(self) -> None:
        """Raise a clear error if Langdock credentials are missing."""
        missing: list[str] = []
        if not self.langdock_api_key:
            missing.append("LANGDOCK_API_KEY")
        if not self.langdock_base_url:
            missing.append("LANGDOCK_BASE_URL")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your shell or in ~/.code-council/env"
            )

    @property
    def plan_path(self) -> Path:
        return Path(self.code_council_plan_dir)


def get_settings() -> Settings:
    """Return a fresh Settings instance (reads current env)."""
    return Settings()
```

### Key Differences from council-me's config.py

- Config directory is `~/.code-council/` (not `~/.councilors/`)
- No user profile system (code-council uses project context, not user profiles)
- Added `code_council_max_negotiation_rounds` setting
- Added `code_council_save_plans` and `code_council_plan_dir` settings
- All env var prefixes use `CODE_COUNCIL_` namespace

---

## 5. Module: llm.py

**File:** `code_council/llm.py`

Same pattern as council-me's `llm.py` (post-0.10.0). A `Protocol` class
defines the interface, a `LangdockLLM` class implements it, and a factory
function creates instances. Tests supply `FakeLLM` instead.

Includes `TokenUsage` and `LLMResult` dataclasses for tracking per-call
token consumption, plus `complete_with_usage()` and `chat_with_usage()`
methods that return token counts alongside text. The original `complete()`
and `chat()` methods remain backward-compatible (return `str`).

### Full Implementation

```python
"""Langdock LLM wrapper.

All provider-specific access lives here. The rest of the codebase calls
complete(prompt, ...) and never talks to the API directly.

Uses the OpenAI Python SDK as a protocol-compatible client pointed at the
Langdock base URL. Swapping the provider later means changing this file only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI

from code_council.config import Settings, get_settings

logger = logging.getLogger(__name__)


Message = dict[str, str]  # {"role": "system"|"user"|"assistant", "content": "..."}


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts from a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResult:
    """Text response plus token usage metadata from an LLM call."""
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Minimal async LLM interface used throughout code-council."""

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
    """Async LLM client that talks to a Langdock OpenAI-compatible endpoint."""

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

        Returns an LLMResult containing the response text and token usage
        counters.
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
                        attempt, max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)

        raise RuntimeError(
            f"LLM call failed after {max_retries} attempts"
        ) from last_exc

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
    """Create a LangdockLLM using the given (or default) settings."""
    return LangdockLLM(settings)
```

### Key Differences from Pre-0.10.0

- `_call_api()` now returns `LLMResult` (text + token usage) instead of `str`
- `complete()` and `chat()` remain backward-compatible (return `str`) by
  extracting `result.text`
- New `complete_with_usage()` and `chat_with_usage()` methods return the
  full `LLMResult` with `TokenUsage` for callers that need token tracking
- `TokenUsage` and `LLMResult` are `@dataclass`es, not Pydantic models
  (lightweight, no validation overhead for internal data)

### Why this is copied rather than shared

The LLM module follows council-me's structure but references
`code_council.config` instead of `councilors.config`, and uses
`code_council_model` and `code_council_agent_timeout_seconds` settings.
Keeping it independent means either project can evolve its LLM layer
without affecting the other.

---

## 6. Module: context.py

**File:** `code_council/context.py`

This module scans the target project's filesystem to build a structured
understanding of the codebase. This context is injected into every advisor
prompt so they can give project-specific advice rather than generic guidance.

### ProjectContext Pydantic Model

```python
from __future__ import annotations

from pydantic import BaseModel


class ProjectContext(BaseModel):
    """Structured representation of a project's codebase for advisor consumption."""

    project_path: str
    """Absolute path to the project root."""

    directory_tree: str
    """Indented directory tree (like `tree` output), excluding ignored dirs."""

    tech_stack: TechStack
    """Detected languages, frameworks, and tools."""

    config_files: dict[str, str]
    """Map of config filename -> file contents (package.json, pyproject.toml, etc.)."""

    relevant_files: dict[str, str]
    """Map of filepath -> file contents for files relevant to the change description."""

    test_patterns: TestPatterns
    """Detected testing conventions."""

    summary: str
    """One-paragraph LLM-generated summary of the project (optional, may be empty)."""


class TechStack(BaseModel):
    """Detected technology stack."""

    languages: list[str]
    """Primary languages (e.g., ["Python", "TypeScript"])."""

    frameworks: list[str]
    """Frameworks detected (e.g., ["FastAPI", "React"])."""

    build_tools: list[str]
    """Build tools (e.g., ["hatchling", "vite"])."""

    package_manager: str
    """Package manager (e.g., "pip", "npm", "pnpm")."""

    runtime: str
    """Runtime (e.g., "python3.11", "node20")."""


class TestPatterns(BaseModel):
    """Detected testing conventions."""

    test_framework: str
    """Testing framework (e.g., "pytest", "jest", "vitest")."""

    test_directories: list[str]
    """Paths to test directories."""

    test_file_pattern: str
    """File naming pattern (e.g., "test_*.py", "*.test.ts")."""

    example_test_files: list[str]
    """Paths to a few representative test files."""
```

### Scanner Functions

```python
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories to always skip when scanning
IGNORED_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist",
    "build", ".next", ".nuxt", "target", ".tox", "egg-info",
    ".eggs", ".DS_Store",
}

# Config files to look for (ordered by priority)
CONFIG_FILES: list[str] = [
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json", "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".env.example", "requirements.txt",
]

# Max file size to read (skip large generated files)
MAX_FILE_SIZE_BYTES: int = 50_000  # 50 KB

# Max number of relevant files to include in context
MAX_RELEVANT_FILES: int = 20


def build_directory_tree(root: Path, max_depth: int = 4) -> str:
    """Build an indented directory tree string.

    Args:
        root: Project root directory.
        max_depth: Maximum depth to recurse.

    Returns:
        Indented tree string like the `tree` command output.
    """
    # Walk the directory tree, skipping IGNORED_DIRS.
    # Each entry is indented by its depth level.
    # Files are listed after directories at each level.
    # Truncate with "..." if a directory has more than 20 entries.
    ...


def detect_tech_stack(root: Path, config_contents: dict[str, str]) -> TechStack:
    """Detect the technology stack from config files and file extensions.

    Logic:
    - If pyproject.toml exists: Python project. Parse for framework hints
      (fastapi, django, flask in dependencies). Build tool from
      [build-system].
    - If package.json exists: JavaScript/TypeScript project. Parse for
      framework hints (react, vue, next, express in dependencies).
    - If Cargo.toml exists: Rust project.
    - If go.mod exists: Go project.
    - Scan file extensions to detect languages.
    - Parse package manager from lock files (poetry.lock, pnpm-lock.yaml,
      yarn.lock, package-lock.json, uv.lock).
    """
    ...


def find_config_files(root: Path) -> dict[str, str]:
    """Find and read config files from CONFIG_FILES list.

    Returns a dict mapping filename to contents.
    Only reads files smaller than MAX_FILE_SIZE_BYTES.
    """
    ...


def detect_test_patterns(root: Path, tech: TechStack) -> TestPatterns:
    """Detect testing conventions.

    Logic:
    - Look for test directories: tests/, test/, __tests__/, spec/
    - Detect framework from config (pytest in pyproject.toml, jest in
      package.json, vitest in vite.config).
    - Detect file naming: test_*.py, *.test.ts, *.spec.ts, *_test.go
    - Find 3-5 representative test files.
    """
    ...


def find_relevant_files(
    root: Path,
    change_description: str,
    max_files: int = MAX_RELEVANT_FILES,
) -> dict[str, str]:
    """Find files relevant to the described change.

    Strategy (no LLM call -- pure heuristics):
    1. Extract keywords from the change description (split on spaces,
       filter stopwords, lowercase).
    2. Walk the project tree (skipping IGNORED_DIRS).
    3. Score each file by:
       - Filename contains a keyword: +3 points
       - File path contains a keyword: +2 points
       - First 200 chars of file content contain a keyword: +1 point
    4. Sort by score descending, take top max_files.
    5. Read and include file contents (skip files > MAX_FILE_SIZE_BYTES).

    Returns a dict mapping relative filepath to contents.
    """
    ...


async def gather_context(
    project_path: str,
    change_description: str,
) -> ProjectContext:
    """Main entry point: gather all project context.

    This is the function called by the planning pipeline.

    Steps:
    1. Validate project_path exists and is a directory.
    2. Build directory tree.
    3. Find and read config files.
    4. Detect tech stack from configs.
    5. Detect test patterns.
    6. Find relevant files based on change description.
    7. Assemble and return ProjectContext.

    Note: This function is async for API consistency but the filesystem
    operations are synchronous (fast enough for local reads). If needed
    in the future, file reads can be moved to a thread pool executor.
    """
    ...
```

### How Context is Consumed

The `ProjectContext` is serialized into a structured text block that gets
injected into every advisor prompt. The format:

```
## Project Context

**Path:** /path/to/project
**Tech Stack:** Python 3.11, FastAPI, React, TypeScript
**Build:** hatchling (Python), vite (frontend)
**Tests:** pytest (tests/), jest (frontend/src/__tests__/)

### Directory Structure
```
src/
  api/
    routes.py
    models.py
  ...
```

### Config Files
[pyproject.toml contents]
[package.json contents]

### Relevant Source Files
[file contents for files matching the change description]
```

This gives each advisor enough context to make project-specific
recommendations rather than generic advice.

---

## 7. Module: advisors.py

**File:** `code_council/advisors.py`

This is the core deliberation engine. It runs code-focused advisors in
parallel, each analyzing the proposed change from a distinct lens. Advisors
are **auto-discovered** from self-describing Markdown files in the `skills/`
directory via YAML frontmatter -- no Python code changes are needed to add,
remove, or update advisors.

This follows the same parallel-execution pattern as council-me's `council.py`
(`asyncio.gather()`, diversity controls via temperature/seed) but replaces
hardcoded advisor definitions with a dynamic skill registry.

### Skill File Format

Each `.md` file in `code_council/skills/` with `type: advisor` in its YAML
frontmatter is automatically discovered and registered. The frontmatter
declares the advisor's identity and diversity parameters:

```yaml
---
name: architect
type: advisor
display_name: Architect Advisor
role_description: >
  You are the Architect Advisor on a Code Council.
  You analyze proposed code changes for structural soundness.
temperature_rank: 4
seed_offset: 4
enabled: true
---
```

The body below the `---` separator is the detailed skill prompt injected
into the advisor's LLM call.

### Skill Registry

```python
"""Code change advisors.

Advisors are auto-discovered from self-describing Markdown files in
code_council/skills/. Each .md file with YAML frontmatter declaring
type: advisor is registered as an advisor.

Adding a new advisor = dropping a new .md file into skills/.
Disabling an advisor = setting enabled: false in its frontmatter.
No Python code changes needed.

Pattern borrowed from council-me's council.py but adapted for code
planning with a dynamic registry rather than hardcoded definitions.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from code_council.context import ProjectContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Protocol (same as llm.py, duplicated here for independence)
# ---------------------------------------------------------------------------

Message = dict[str, str]


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Skill data model
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).parent / "skills"


@dataclass
class AdvisorSkill:
    """A single advisor skill discovered from a .md file."""

    name: str
    """Internal name (e.g., 'architect'). Used for seed generation."""

    display_name: str
    """Human-readable name (e.g., 'Architect Advisor')."""

    role_description: str
    """Short role description injected into the prompt preamble."""

    skill_text: str
    """Full Markdown body (below the frontmatter) injected as skill reference."""

    temperature_rank: int
    """Rank for temperature assignment (0 = lowest/most concrete)."""

    seed_offset: int
    """Offset added to the base seed for this advisor."""

    enabled: bool = True
    """Whether this advisor is active. Set to False to skip it."""

    source_path: str = ""
    """Path to the source .md file (for debugging)."""


# ---------------------------------------------------------------------------
# Skill registry -- discovery and loading
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown file.

    Expects the file to start with '---', followed by YAML, followed by
    another '---', then the Markdown body.

    Returns:
        Tuple of (frontmatter_dict, body_text).
        If no frontmatter is found, returns ({}, full_text).
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end = text.find("---", 3)
    if end == -1:
        return {}, text

    yaml_text = text[3:end].strip()
    body = text[end + 3:].strip()

    try:
        frontmatter = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse YAML frontmatter: %s", exc)
        return {}, text

    return frontmatter, body


def discover_advisor_skills(
    skills_dir: Path | None = None,
) -> list[AdvisorSkill]:
    """Scan the skills directory and return all enabled advisor skills.

    Reads every .md file in the directory, parses YAML frontmatter,
    and constructs AdvisorSkill instances for files with type: advisor
    and enabled: true.

    Skills are sorted by temperature_rank (ascending) for deterministic
    ordering.

    Args:
        skills_dir: Directory to scan. Defaults to code_council/skills/.

    Returns:
        List of AdvisorSkill instances, sorted by temperature_rank.
    """
    skills_dir = skills_dir or _SKILLS_DIR
    if not skills_dir.is_dir():
        logger.warning("Skills directory not found: %s", skills_dir)
        return []

    skills: list[AdvisorSkill] = []

    for path in sorted(skills_dir.glob("*.md")):
        try:
            text = path.read_text()
        except OSError as exc:
            logger.warning("Failed to read skill file %s: %s", path, exc)
            continue

        frontmatter, body = _parse_frontmatter(text)

        # Skip files without frontmatter or wrong type
        if frontmatter.get("type") != "advisor":
            continue

        # Skip disabled skills
        if not frontmatter.get("enabled", True):
            logger.info("Skipping disabled skill: %s", path.name)
            continue

        # Validate required fields
        name = frontmatter.get("name", "")
        if not name:
            logger.warning("Skill file %s missing 'name' in frontmatter", path)
            continue

        skill = AdvisorSkill(
            name=name,
            display_name=frontmatter.get("display_name", name.title()),
            role_description=frontmatter.get("role_description", ""),
            skill_text=body,
            temperature_rank=int(frontmatter.get("temperature_rank", 0)),
            seed_offset=int(frontmatter.get("seed_offset", 0)),
            enabled=True,
            source_path=str(path),
        )
        skills.append(skill)

    # Sort by temperature_rank for deterministic ordering
    skills.sort(key=lambda s: s.temperature_rank)

    logger.info(
        "Discovered %d advisor skills: %s",
        len(skills),
        [s.name for s in skills],
    )
    return skills


def discover_synthesizer_skill(
    skills_dir: Path | None = None,
) -> str:
    """Load the synthesizer skill (type: synthesizer) from the skills directory.

    Returns the Markdown body of the first enabled file with
    type: synthesizer, or an empty string if none found.
    """
    skills_dir = skills_dir or _SKILLS_DIR
    if not skills_dir.is_dir():
        return ""

    for path in sorted(skills_dir.glob("*.md")):
        try:
            text = path.read_text()
        except OSError:
            continue

        frontmatter, body = _parse_frontmatter(text)
        if frontmatter.get("type") == "synthesizer" and frontmatter.get("enabled", True):
            return body

    logger.warning("No synthesizer skill found in %s", skills_dir)
    return ""


# ---------------------------------------------------------------------------
# Diversity controls
# ---------------------------------------------------------------------------


def _advisor_temperature(rank: int, total_advisors: int, spread: float) -> float:
    """Return a temperature for an advisor based on rank, total count, and spread.

    Temperatures are evenly spaced from (1.0 - spread) to 1.0.
    Adapts automatically to however many advisors are active.
    """
    if spread <= 0.0 or total_advisors <= 1:
        return 1.0
    return round(1.0 - spread + (spread * rank / (total_advisors - 1)), 3)


def _advisor_seed(seed_offset: int, plan_id: str) -> int:
    """Deterministic seed derived from plan_id and advisor seed_offset."""
    base = int(hashlib.sha256(plan_id.encode()).hexdigest()[:8], 16)
    return base + seed_offset
```

### Advisor Prompt Builder

```python
def _format_context(ctx: ProjectContext) -> str:
    """Format a ProjectContext into a text block for injection into prompts."""
    parts = [
        f"## Project Context\n",
        f"**Path:** {ctx.project_path}",
        f"**Languages:** {', '.join(ctx.tech_stack.languages)}",
        f"**Frameworks:** {', '.join(ctx.tech_stack.frameworks)}",
        f"**Build:** {', '.join(ctx.tech_stack.build_tools)}",
        f"**Tests:** {ctx.test_patterns.test_framework} "
        f"({', '.join(ctx.test_patterns.test_directories)})",
        "",
        "### Directory Structure",
        f"```\n{ctx.directory_tree}\n```",
    ]

    if ctx.config_files:
        parts.append("\n### Config Files")
        for name, content in ctx.config_files.items():
            parts.append(f"\n**{name}:**\n```\n{content}\n```")

    if ctx.relevant_files:
        parts.append("\n### Relevant Source Files")
        for path, content in ctx.relevant_files.items():
            parts.append(f"\n**{path}:**\n```\n{content}\n```")

    return "\n".join(parts)


def _advisor_prompt(
    skill: AdvisorSkill,
    change_description: str,
    context: ProjectContext,
    negotiation_feedback: str = "",
) -> str:
    """Build the full prompt for a single advisor.

    Args:
        skill: The advisor's skill definition (from registry).
        change_description: What the user wants to change.
        context: The gathered project context.
        negotiation_feedback: If this is a re-run after a failed
            negotiation, this contains the AI tool's concerns.
    """
    parts = []

    if skill.skill_text:
        parts.append(f"## Advisor Skill Reference\n\n{skill.skill_text}\n\n---\n")

    parts.append(_format_context(context))
    parts.append("\n---\n")
    parts.append(f"{skill.role_description}\n\n")
    parts.append(
        "A user wants to make the following change to this codebase:\n\n"
        "---\n"
        f"{change_description}\n"
        "---\n\n"
    )

    if negotiation_feedback:
        parts.append(
            "## AI Tool Feedback (from previous review)\n\n"
            "The AI coding tool reviewed the previous plan and raised "
            "these concerns. Factor them into your analysis:\n\n"
            f"{negotiation_feedback}\n\n---\n\n"
        )

    parts.append(
        "Analyze this change from your specific perspective. "
        "Be direct and specific to THIS codebase -- reference actual "
        "files, patterns, and conventions you see in the project context. "
        "Do not give generic advice.\n\n"
        "Keep your response between 150-300 words. No preamble. "
        "Go straight into your analysis."
    )
    return "\n".join(parts)
```

### Run Advisors (parallel)

```python
async def run_advisors(
    change_description: str,
    context: ProjectContext,
    llm: LLMClient,
    plan_id: str,
    temperature_spread: float = 0.4,
    negotiation_feedback: str = "",
    skills_dir: Path | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, float]]:
    """Run all discovered advisors in parallel and return their responses.

    Advisors are auto-discovered from .md files in the skills directory.
    The number of advisors adapts to however many enabled skill files exist.

    Args:
        change_description: What the user wants to change.
        context: The gathered project context.
        llm: LLM client instance.
        plan_id: Unique plan identifier (used for seed generation).
        temperature_spread: Temperature variation range.
        negotiation_feedback: AI tool's concerns from a prior round.
        skills_dir: Override skills directory (for testing).

    Returns:
        Tuple of:
        - advisor_responses: dict[display_name, response_text]
        - advisor_params: dict[display_name, {temperature, seed}]
        - stage_timing: dict with "start" and "duration" keys
    """
    skills = discover_advisor_skills(skills_dir)
    if not skills:
        raise RuntimeError("No advisor skills found. Check the skills/ directory.")

    total = len(skills)

    # Compute per-advisor temperature and seed
    advisor_params: dict[str, dict[str, Any]] = {}
    for skill in skills:
        advisor_params[skill.display_name] = {
            "temperature": _advisor_temperature(
                skill.temperature_rank, total, temperature_spread,
            ),
            "seed": _advisor_seed(skill.seed_offset, plan_id),
        }

    async def _run_one(skill: AdvisorSkill) -> tuple[str, str]:
        prompt = _advisor_prompt(
            skill,
            change_description,
            context,
            negotiation_feedback,
        )
        params = advisor_params[skill.display_name]
        response = await llm.complete(
            prompt,
            temperature=params["temperature"],
            seed=params["seed"],
        )
        return skill.display_name, response

    t0 = time.monotonic()
    results = await asyncio.gather(*[_run_one(s) for s in skills])
    duration = time.monotonic() - t0

    advisor_responses: dict[str, str] = dict(results)
    timing = {"start": t0, "duration": round(duration, 3)}

    return advisor_responses, advisor_params, timing
```

### Natural Tensions Between Advisors

| Tension | Advisors |
|---|---|
| Structure vs Speed | Architect vs Executor |
| Safety vs Velocity | Security vs Executor |
| Quality vs Scope | Quality vs Risk |
| Ideal vs Pragmatic | Architect vs Risk |
| Detail vs Big Picture | Quality vs Architect |
| Value vs Effort | Business vs Executor |
| Scope vs Purity | Business vs Architect |
| Ship vs Wait | Business vs Risk |
| Feature vs Quality | Business vs Quality |

These tensions are by design -- they force the synthesizer to make trade-offs
rather than producing a plan that satisfies no one. The Business advisor adds
a strategic dimension that prevents the council from being purely technical.

---

## 8. Module: synthesizer.py

**File:** `code_council/synthesizer.py`

The synthesizer takes all 5 advisor responses and produces a structured
`ChangePlan`. This is analogous to council-me's Chairman but focused on
producing an actionable implementation plan rather than a verdict.

### ChangePlan Pydantic Model

```python
"""Plan synthesis from advisor outputs.

Receives all 5 advisor analyses and produces a structured ChangePlan
with affected files, implementation steps, sequencing, risks, and
acceptance criteria.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from code_council.context import ProjectContext

logger = logging.getLogger(__name__)

Message = dict[str, str]


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str: ...


# ---------------------------------------------------------------------------
# ChangePlan data model
# ---------------------------------------------------------------------------


class ImplementationStep(BaseModel):
    """A single step in the implementation plan."""

    order: int
    """Execution order (1-based)."""

    file_path: str
    """Relative path to the file being changed."""

    action: str
    """What to do: 'create', 'modify', 'delete', 'rename'."""

    description: str
    """What specifically to change in this file and why."""

    depends_on: list[int]
    """Step numbers that must be completed before this one."""


class ChangePlan(BaseModel):
    """Structured implementation plan produced by the synthesizer."""

    plan_id: str
    """Unique identifier for this plan."""

    title: str
    """Short title for the change (e.g., 'Add user authentication to API')."""

    summary: str
    """One-paragraph summary of what is being changed and why."""

    change_description: str
    """The original change description from the user."""

    affected_files: list[str]
    """All files that will be created, modified, or deleted."""

    implementation_steps: list[ImplementationStep]
    """Ordered list of implementation steps."""

    architecture_notes: str
    """Summary from the Architect advisor."""

    security_notes: str
    """Summary from the Security advisor."""

    quality_notes: str
    """Summary from the Quality advisor -- including test changes needed."""

    risk_assessment: str
    """Summary from the Risk advisor -- risk level and mitigations."""

    execution_strategy: str
    """Summary from the Executor advisor -- phasing, effort estimate."""

    acceptance_criteria: list[str]
    """Checklist of conditions that must be true when the change is complete."""

    estimated_effort: str
    """Effort estimate: S / M / L / XL."""

    risk_level: str
    """Overall risk: LOW / MEDIUM / HIGH."""

    negotiation_round: int = 0
    """Which negotiation round produced this plan (0 = first pass)."""

    raw_advisor_responses: dict[str, str] = {}
    """Full advisor responses for audit/reference."""
```

### Synthesizer Prompt

```python
_SKILLS_DIR = Path(__file__).parent / "skills"


def _load_synthesizer_skill() -> str:
    """Load the synthesizer skill prompt."""
    path = _SKILLS_DIR / "synthesizer.md"
    if path.is_file():
        return path.read_text()
    logger.warning("Synthesizer skill not found at %s", path)
    return ""


def _synthesizer_prompt(
    change_description: str,
    advisor_responses: dict[str, str],
    context: ProjectContext,
) -> str:
    """Build the prompt for the plan synthesizer.

    The synthesizer receives:
    - The original change description
    - All 5 advisor responses (not anonymized -- the synthesizer needs
      to know which perspective each came from)
    - Project context summary
    """
    skill_text = _load_synthesizer_skill()

    advisor_section = "\n\n".join(
        f"**{name} Advisor:**\n{text}"
        for name, text in advisor_responses.items()
    )

    tech_summary = (
        f"Languages: {', '.join(context.tech_stack.languages)}, "
        f"Frameworks: {', '.join(context.tech_stack.frameworks)}, "
        f"Tests: {context.test_patterns.test_framework}"
    )

    parts = []
    if skill_text:
        parts.append(f"{skill_text}\n\n---\n")

    parts.append(
        "You are the Plan Synthesizer for a Code Council. Your job is to "
        "take the analyses from 5 code advisors and produce a single, "
        "structured implementation plan.\n\n"
        f"**Project:** {context.project_path}\n"
        f"**Stack:** {tech_summary}\n\n"
        "The user wants to make this change:\n\n"
        "---\n"
        f"{change_description}\n"
        "---\n\n"
        f"ADVISOR ANALYSES:\n\n{advisor_section}\n\n"
        "---\n\n"
        "Produce the implementation plan using this EXACT structure. "
        "Use valid JSON that can be parsed programmatically:\n\n"
        "```json\n"
        "{\n"
        '  "title": "Short title for the change",\n'
        '  "summary": "One paragraph summary",\n'
        '  "affected_files": ["path/to/file1.py", "path/to/file2.py"],\n'
        '  "implementation_steps": [\n'
        "    {\n"
        '      "order": 1,\n'
        '      "file_path": "path/to/file.py",\n'
        '      "action": "modify",\n'
        '      "description": "What to change and why",\n'
        '      "depends_on": []\n'
        "    }\n"
        "  ],\n"
        '  "architecture_notes": "Summary from architect perspective",\n'
        '  "security_notes": "Summary from security perspective",\n'
        '  "quality_notes": "Test changes needed, quality impact",\n'
        '  "risk_assessment": "Risk level and mitigations",\n'
        '  "execution_strategy": "Phasing and effort",\n'
        '  "acceptance_criteria": [\n'
        '    "All existing tests pass",\n'
        '    "New unit tests added for ...",\n'
        '    "No breaking changes to public API"\n'
        "  ],\n"
        '  "estimated_effort": "M",\n'
        '  "risk_level": "MEDIUM"\n'
        "}\n"
        "```\n\n"
        "Rules:\n"
        "- Be specific to THIS codebase. Reference actual files and patterns.\n"
        "- Implementation steps must be ordered by dependency.\n"
        "- Every file mentioned in steps must appear in affected_files.\n"
        "- Acceptance criteria must be verifiable (testable, not vague).\n"
        "- If advisors disagree, make a judgment call and note the trade-off.\n"
        "- Risk level must be one of: LOW, MEDIUM, HIGH.\n"
        "- Effort must be one of: S, M, L, XL."
    )
    return "\n".join(parts)
```

### Synthesis Function

```python
import json


async def synthesize_plan(
    change_description: str,
    advisor_responses: dict[str, str],
    context: ProjectContext,
    plan_id: str,
    llm: LLMClient,
    negotiation_round: int = 0,
) -> ChangePlan:
    """Synthesize a ChangePlan from advisor responses.

    Args:
        change_description: The original change description.
        advisor_responses: All 5 advisor responses.
        context: Project context.
        plan_id: Unique plan identifier.
        llm: LLM client instance.
        negotiation_round: Current negotiation round (0 = first pass).

    Returns:
        A ChangePlan instance.

    The LLM is asked to produce JSON output. This function parses the JSON
    and constructs the ChangePlan model. If JSON parsing fails, it retries
    once with a repair prompt.
    """
    prompt = _synthesizer_prompt(change_description, advisor_responses, context)

    raw_response = await llm.complete(prompt)

    # Extract JSON from the response (may be wrapped in ```json ... ```)
    json_text = _extract_json(raw_response)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        # Retry with a repair prompt
        repair_prompt = (
            "The previous response was not valid JSON. "
            "Please fix the JSON and return ONLY the corrected JSON block:\n\n"
            f"{raw_response}"
        )
        raw_response = await llm.complete(repair_prompt)
        json_text = _extract_json(raw_response)
        data = json.loads(json_text)

    return ChangePlan(
        plan_id=plan_id,
        change_description=change_description,
        negotiation_round=negotiation_round,
        raw_advisor_responses=advisor_responses,
        **data,
    )


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown code fences.

    Looks for ```json ... ``` blocks first, then tries the raw text.
    """
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    return text.strip()
```

---

## 9. Module: state.py and storage.py

### state.py -- Plan State Machine

**File:** `code_council/state.py`

Each plan has a lifecycle. The state machine prevents invalid transitions
(e.g., executing a plan that hasn't been reviewed).

```python
"""Plan state machine.

Manages the lifecycle of a change plan through its stages:
  drafting -> proposed -> reviewing -> agreed -> executing -> completed

Also supports: rejected (terminal), stalled (needs human intervention).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PlanStatus(str, Enum):
    """Valid plan states."""

    DRAFTING = "drafting"       # Advisors are running, plan not yet ready
    PROPOSED = "proposed"       # Plan synthesized, waiting for AI tool review
    REVIEWING = "reviewing"     # AI tool is reviewing the plan
    AGREED = "agreed"           # Both council and AI tool agree on the plan
    EXECUTING = "executing"     # AI tool is implementing the plan
    COMPLETED = "completed"     # Implementation finished
    REJECTED = "rejected"       # AI tool rejected and max rounds exceeded
    STALLED = "stalled"         # Needs human intervention


# Valid transitions: from_state -> set of allowed to_states
VALID_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    PlanStatus.DRAFTING:  {PlanStatus.PROPOSED},
    PlanStatus.PROPOSED:  {PlanStatus.REVIEWING},
    PlanStatus.REVIEWING: {PlanStatus.AGREED, PlanStatus.DRAFTING, PlanStatus.REJECTED, PlanStatus.STALLED},
    PlanStatus.AGREED:    {PlanStatus.EXECUTING},
    PlanStatus.EXECUTING: {PlanStatus.COMPLETED},
    PlanStatus.COMPLETED: set(),  # terminal
    PlanStatus.REJECTED:  {PlanStatus.DRAFTING},  # can restart
    PlanStatus.STALLED:   {PlanStatus.DRAFTING},  # can restart
}


class NegotiationRound(BaseModel):
    """Record of a single negotiation round."""

    round_number: int
    concerns: list[str]
    suggestions: list[str]
    plan_changes_made: list[str]


class PlanState(BaseModel):
    """Tracks the current state and history of a plan."""

    plan_id: str
    status: PlanStatus = PlanStatus.DRAFTING
    negotiation_round: int = 0
    max_rounds: int = 3
    negotiation_history: list[NegotiationRound] = []
    error_message: str = ""

    def transition(self, new_status: PlanStatus) -> None:
        """Transition to a new status. Raises ValueError on invalid transition."""
        if new_status not in VALID_TRANSITIONS.get(self.status, set()):
            raise ValueError(
                f"Invalid transition: {self.status.value} -> {new_status.value}. "
                f"Valid targets: {[s.value for s in VALID_TRANSITIONS.get(self.status, set())]}"
            )
        logger.info("Plan %s: %s -> %s", self.plan_id, self.status.value, new_status.value)
        self.status = new_status

    def can_negotiate(self) -> bool:
        """Check if another negotiation round is allowed."""
        return self.negotiation_round < self.max_rounds

    def record_negotiation(
        self,
        concerns: list[str],
        suggestions: list[str],
        plan_changes: list[str],
    ) -> None:
        """Record a completed negotiation round."""
        self.negotiation_round += 1
        self.negotiation_history.append(
            NegotiationRound(
                round_number=self.negotiation_round,
                concerns=concerns,
                suggestions=suggestions,
                plan_changes_made=plan_changes,
            )
        )
```

### storage.py -- Plan Persistence

**File:** `code_council/storage.py`

Saves plans as JSON files, following the same pattern as council-me's
transcript storage.

```python
"""Plan storage for code-council.

Saves each plan as a JSON file under the configured plan directory.
Provides queries for recent plans and lookup by ID.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code_council.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_plan(
    *,
    plan_id: str,
    change_description: str,
    plan_data: dict[str, Any],
    state_data: dict[str, Any],
    advisor_responses: dict[str, str],
    context_summary: str,
    settings: Settings | None = None,
) -> Path | None:
    """Persist a plan as JSON. Returns the file path or None if disabled."""
    settings = settings or get_settings()
    if not settings.code_council_save_plans:
        return None

    plan_dir = settings.plan_path
    _ensure_dir(plan_dir)

    ts = datetime.now(timezone.utc).isoformat()
    filename = f"plan-{plan_id}.json"
    path = plan_dir / filename

    data: dict[str, Any] = {
        "plan_id": plan_id,
        "timestamp": ts,
        "change_description": change_description,
        "plan": plan_data,
        "state": state_data,
        "advisor_responses": advisor_responses,
        "context_summary": context_summary,
    }

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Plan saved to %s", path)
    return path


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_plan(plan_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    """Load a plan by ID. Returns the plan dict or None if not found."""
    settings = settings or get_settings()
    path = settings.plan_path / f"plan-{plan_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load plan %s: %s", plan_id, exc)
        return None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def list_recent_plans(
    limit: int = 10,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return metadata for the most recent plans."""
    settings = settings or get_settings()
    plan_dir = settings.plan_path
    if not plan_dir.is_dir():
        return []

    files = sorted(
        plan_dir.glob("plan-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    results: list[dict[str, Any]] = []
    for fp in files[:limit]:
        try:
            data = json.loads(fp.read_text())
            results.append({
                "plan_id": data.get("plan_id", ""),
                "timestamp": data.get("timestamp", ""),
                "change_description": (data.get("change_description", ""))[:120],
                "status": data.get("state", {}).get("status", "unknown"),
                "risk_level": data.get("plan", {}).get("risk_level", ""),
                "effort": data.get("plan", {}).get("estimated_effort", ""),
            })
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping unreadable plan %s: %s", fp, exc)

    return results


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_plan(plan_id: str, settings: Settings | None = None) -> bool:
    """Delete a plan by ID. Returns True if deleted."""
    settings = settings or get_settings()
    path = settings.plan_path / f"plan-{plan_id}.json"
    if path.is_file():
        path.unlink()
        logger.info("Plan deleted: %s", path)
        return True
    return False
```

---

## 10. Module: mcp_server.py

**File:** `code_council/mcp_server.py`

This is the primary interface. It exposes Code Council as an MCP server
that AI coding tools connect to via STDIO transport. Uses the Python MCP
SDK's `FastMCP` class for minimal boilerplate.

### MCP Server Setup

```python
"""MCP server for Code Council.

Exposes planning tools, resources, and prompts via the Model Context
Protocol. AI coding tools (Cursor, Copilot, OpenCode) connect to this
server via STDIO transport.

Run with:
    code-council serve          # via CLI
    uv run code-council serve   # via uv
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from code_council.config import get_settings
from code_council.context import gather_context
from code_council.advisors import run_advisors
from code_council.synthesizer import synthesize_plan, ChangePlan
from code_council.negotiation import negotiate_plan
from code_council.state import PlanState, PlanStatus
from code_council.storage import save_plan, load_plan, list_recent_plans
from code_council.llm import get_llm

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(
    "code-council",
    version="0.1.0",
    description="Plans code changes through multi-advisor deliberation",
)

# ---------------------------------------------------------------------------
# In-memory plan registry (active plans for this session)
# ---------------------------------------------------------------------------

_active_plans: dict[str, dict[str, Any]] = {}
# Structure: {plan_id: {"plan": ChangePlan, "state": PlanState, "context": ProjectContext}}
```

### Tool: plan_changes

```python
@mcp.tool()
async def plan_changes(
    description: str,
    project_path: str = ".",
) -> str:
    """Plan code changes through multi-advisor deliberation.

    Describe the change you want to make. Code Council will:
    1. Scan the project for context (files, tech stack, patterns)
    2. Run 5 advisors in parallel (Architect, Security, Quality, Risk, Executor)
    3. Synthesize a structured implementation plan

    Args:
        description: What you want to change (e.g., "Add user authentication
            to the REST API using JWT tokens")
        project_path: Path to the project root. Defaults to current directory.

    Returns:
        A structured implementation plan in JSON format.
    """
    settings = get_settings()
    llm = get_llm(settings)
    plan_id = uuid.uuid4().hex[:12]

    # Step 1: Gather project context
    context = await gather_context(project_path, description)

    # Step 2: Initialize plan state
    state = PlanState(
        plan_id=plan_id,
        max_rounds=settings.code_council_max_negotiation_rounds,
    )

    # Step 3: Run advisors
    advisor_responses, advisor_params, timing = await run_advisors(
        change_description=description,
        context=context,
        llm=llm,
        plan_id=plan_id,
        temperature_spread=settings.code_council_advisor_temperature_spread,
    )

    # Step 4: Synthesize plan
    plan = await synthesize_plan(
        change_description=description,
        advisor_responses=advisor_responses,
        context=context,
        plan_id=plan_id,
        llm=llm,
    )

    # Step 5: Update state
    state.transition(PlanStatus.PROPOSED)

    # Step 6: Store in memory and on disk
    _active_plans[plan_id] = {
        "plan": plan,
        "state": state,
        "context": context,
    }

    save_plan(
        plan_id=plan_id,
        change_description=description,
        plan_data=plan.model_dump(),
        state_data=state.model_dump(),
        advisor_responses=advisor_responses,
        context_summary=context.summary,
        settings=settings,
    )

    # Return the plan as formatted text for the AI tool to review
    return _format_plan_for_review(plan, state)
```

### Tool: review_plan

```python
@mcp.tool()
async def review_plan(
    plan_id: str,
    feasible: bool,
    concerns: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> str:
    """Submit your feasibility assessment of a plan.

    After receiving a plan from plan_changes, review it against the actual
    codebase and submit your assessment. If infeasible, provide specific
    concerns -- the council will reassess.

    Args:
        plan_id: The plan ID from the plan_changes response.
        feasible: True if the plan is feasible as-is, False if it needs changes.
        concerns: List of specific technical concerns (required if infeasible).
        suggestions: List of alternative approaches to consider.

    Returns:
        If feasible: confirmation that the plan is agreed and ready to execute.
        If infeasible: an updated plan incorporating your feedback.
    """
    concerns = concerns or []
    suggestions = suggestions or []

    if plan_id not in _active_plans:
        return f"Error: Plan '{plan_id}' not found. Use plan_changes to create a plan first."

    entry = _active_plans[plan_id]
    state: PlanState = entry["state"]

    # Transition to reviewing
    state.transition(PlanStatus.REVIEWING)

    if feasible:
        # Plan accepted
        state.transition(PlanStatus.AGREED)
        entry["state"] = state
        return (
            f"Plan '{plan_id}' is AGREED. Both the council and you are aligned.\n\n"
            f"Call execute_plan(plan_id='{plan_id}') when you're ready to "
            "receive step-by-step implementation instructions."
        )

    # Plan rejected -- negotiate
    if not state.can_negotiate():
        state.transition(PlanStatus.STALLED)
        entry["state"] = state
        return (
            f"Plan '{plan_id}' is STALLED after {state.negotiation_round} "
            "negotiation rounds. The council and AI tool could not reach "
            "agreement. Human intervention is needed.\n\n"
            f"Council's latest plan:\n{_format_plan_for_review(entry['plan'], state)}\n\n"
            f"Your concerns:\n" + "\n".join(f"- {c}" for c in concerns)
        )

    # Re-run advisors with feedback, re-synthesize
    settings = get_settings()
    llm = get_llm(settings)

    updated_plan = await negotiate_plan(
        plan=entry["plan"],
        state=state,
        context=entry["context"],
        concerns=concerns,
        suggestions=suggestions,
        llm=llm,
        settings=settings,
    )

    entry["plan"] = updated_plan
    entry["state"] = state

    # Save updated plan
    save_plan(
        plan_id=plan_id,
        change_description=updated_plan.change_description,
        plan_data=updated_plan.model_dump(),
        state_data=state.model_dump(),
        advisor_responses=updated_plan.raw_advisor_responses,
        context_summary=entry["context"].summary,
        settings=settings,
    )

    return (
        f"Plan '{plan_id}' updated (round {state.negotiation_round}/{state.max_rounds}).\n\n"
        "Changes made based on your feedback:\n"
        + "\n".join(f"- {c}" for c in state.negotiation_history[-1].plan_changes_made)
        + "\n\n"
        + _format_plan_for_review(updated_plan, state)
    )
```

### Tool: execute_plan

```python
@mcp.tool()
async def execute_plan(plan_id: str) -> str:
    """Get step-by-step implementation instructions for an agreed plan.

    Only works on plans with status 'agreed'. Returns a detailed prompt
    that guides the AI coding tool through the implementation.

    Args:
        plan_id: The plan ID to execute.

    Returns:
        Step-by-step implementation instructions.
    """
    if plan_id not in _active_plans:
        return f"Error: Plan '{plan_id}' not found."

    entry = _active_plans[plan_id]
    state: PlanState = entry["state"]
    plan: ChangePlan = entry["plan"]

    if state.status != PlanStatus.AGREED:
        return (
            f"Error: Plan '{plan_id}' is in status '{state.status.value}'. "
            "Only agreed plans can be executed. "
            "Call review_plan first to agree on the plan."
        )

    state.transition(PlanStatus.EXECUTING)
    entry["state"] = state

    return _format_execution_prompt(plan)
```

### Tool: get_plan

```python
@mcp.tool()
async def get_plan(plan_id: str) -> str:
    """Retrieve a plan by ID.

    Args:
        plan_id: The plan ID to look up.

    Returns:
        The plan contents and current status.
    """
    if plan_id in _active_plans:
        entry = _active_plans[plan_id]
        return _format_plan_for_review(entry["plan"], entry["state"])

    # Try loading from disk
    data = load_plan(plan_id)
    if data:
        return json.dumps(data, indent=2)

    return f"Error: Plan '{plan_id}' not found."
```

### Tool: get_plan_status

```python
@mcp.tool()
async def get_plan_status(plan_id: str) -> str:
    """Check the current status of a plan.

    Args:
        plan_id: The plan ID to check.

    Returns:
        Status information including current state and negotiation round.
    """
    if plan_id in _active_plans:
        state = _active_plans[plan_id]["state"]
        return json.dumps({
            "plan_id": plan_id,
            "status": state.status.value,
            "negotiation_round": state.negotiation_round,
            "max_rounds": state.max_rounds,
            "can_negotiate": state.can_negotiate(),
        }, indent=2)

    return f"Error: Plan '{plan_id}' not found in active plans."
```

### Tool: list_plans

```python
@mcp.tool()
async def list_plans() -> str:
    """List recent plans with their statuses.

    Returns:
        JSON array of recent plan metadata.
    """
    plans = list_recent_plans()
    if not plans:
        return "No plans found."
    return json.dumps(plans, indent=2)
```

### MCP Resources

```python
@mcp.resource("plan://current")
async def get_current_plan() -> str:
    """The most recently created or updated plan."""
    if not _active_plans:
        return "No active plans."
    # Get the most recently modified plan
    latest_id = max(
        _active_plans.keys(),
        key=lambda pid: _active_plans[pid]["state"].negotiation_round,
    )
    entry = _active_plans[latest_id]
    return _format_plan_for_review(entry["plan"], entry["state"])


@mcp.resource("plan://plans/{plan_id}")
async def get_plan_resource(plan_id: str) -> str:
    """A specific plan by ID."""
    if plan_id in _active_plans:
        entry = _active_plans[plan_id]
        return _format_plan_for_review(entry["plan"], entry["state"])
    return f"Plan '{plan_id}' not found."
```

### MCP Prompt Template

```python
@mcp.prompt()
async def review_and_plan() -> str:
    """Pre-built prompt template that guides the AI tool through
    the full plan-review-execute workflow.

    Use this prompt when you want to plan code changes.
    """
    return (
        "You are about to plan code changes using Code Council.\n\n"
        "## Workflow\n\n"
        "1. **Describe the change**: Tell me what you want to change.\n"
        "   I will call `plan_changes` with your description.\n\n"
        "2. **Review the plan**: I will receive a structured plan from\n"
        "   the council. I should review it against the actual codebase:\n"
        "   - Check that referenced files exist\n"
        "   - Verify the implementation steps make sense\n"
        "   - Identify any missing dependencies or steps\n\n"
        "3. **Submit review**: Call `review_plan` with my assessment.\n"
        "   - If feasible: set feasible=true\n"
        "   - If not: set feasible=false with specific concerns\n\n"
        "4. **Iterate if needed**: If infeasible, the council will\n"
        "   reassess. Review the updated plan.\n\n"
        "5. **Execute**: Once agreed, call `execute_plan` to get\n"
        "   step-by-step implementation instructions.\n\n"
        "6. **Implement**: Follow the instructions to make the changes.\n"
    )
```

### Helper: Format Plan for Review

```python
def _format_plan_for_review(plan: ChangePlan, state: PlanState) -> str:
    """Format a ChangePlan as readable text for AI tool review."""
    steps_text = "\n".join(
        f"  {s.order}. [{s.action.upper()}] `{s.file_path}`\n"
        f"     {s.description}\n"
        f"     Depends on: {s.depends_on if s.depends_on else 'none'}"
        for s in plan.implementation_steps
    )

    criteria_text = "\n".join(f"  - [ ] {c}" for c in plan.acceptance_criteria)

    return (
        f"# Change Plan: {plan.title}\n"
        f"**Plan ID:** `{plan.plan_id}`\n"
        f"**Status:** {state.status.value}\n"
        f"**Round:** {state.negotiation_round}/{state.max_rounds}\n"
        f"**Risk:** {plan.risk_level} | **Effort:** {plan.estimated_effort}\n\n"
        f"## Summary\n{plan.summary}\n\n"
        f"## Affected Files\n"
        + "\n".join(f"- `{f}`" for f in plan.affected_files)
        + f"\n\n## Implementation Steps\n{steps_text}\n\n"
        f"## Architecture Notes\n{plan.architecture_notes}\n\n"
        f"## Security Notes\n{plan.security_notes}\n\n"
        f"## Quality & Test Notes\n{plan.quality_notes}\n\n"
        f"## Risk Assessment\n{plan.risk_assessment}\n\n"
        f"## Execution Strategy\n{plan.execution_strategy}\n\n"
        f"## Acceptance Criteria\n{criteria_text}\n"
    )
```

### Helper: Format Execution Prompt

```python
def _format_execution_prompt(plan: ChangePlan) -> str:
    """Format a ChangePlan as an implementation prompt for the AI tool."""
    steps = []
    for s in plan.implementation_steps:
        dep_note = ""
        if s.depends_on:
            dep_note = f" (do this AFTER steps {s.depends_on})"
        steps.append(
            f"### Step {s.order}: {s.action.upper()} `{s.file_path}`{dep_note}\n\n"
            f"{s.description}\n"
        )

    criteria = "\n".join(f"- [ ] {c}" for c in plan.acceptance_criteria)

    return (
        f"# Implementation Instructions: {plan.title}\n\n"
        "Follow these steps in order. Each step specifies the file to "
        "change, the action to take, and what specifically to do.\n\n"
        "## Steps\n\n"
        + "\n".join(steps)
        + f"\n## Security Considerations\n\n{plan.security_notes}\n\n"
        f"## Quality Requirements\n\n{plan.quality_notes}\n\n"
        f"## Verification Checklist\n\n{criteria}\n\n"
        "After completing all steps, verify ALL acceptance criteria are met "
        "before considering the implementation complete."
    )
```

### Server Entry Point

```python
def run_server() -> None:
    """Start the MCP server on STDIO transport.

    This is called by the CLI's `serve` command.
    """
    mcp.run(transport="stdio")
```

---

## 11. Module: negotiation.py

**File:** `code_council/negotiation.py`

The negotiation engine handles the back-and-forth between the council and
the AI coding tool. When the AI tool says a plan is infeasible, this module
re-runs the advisors with the AI tool's feedback injected and produces a
revised plan.

### Full Implementation

```python
"""Feasibility negotiation loop.

When the AI tool rejects a plan, this module re-runs the advisors with
the tool's feedback injected as additional context, then re-synthesizes.

The negotiation follows this cycle:
  1. AI tool submits concerns and suggestions via review_plan()
  2. Advisors re-run with the feedback injected into their prompts
  3. Synthesizer produces an updated plan
  4. Updated plan is sent back to the AI tool for another review
  5. Repeat up to max_rounds, then stall for human intervention
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from code_council.advisors import run_advisors
from code_council.config import Settings
from code_council.context import ProjectContext
from code_council.state import PlanState, PlanStatus
from code_council.synthesizer import ChangePlan, synthesize_plan

logger = logging.getLogger(__name__)

Message = dict[str, str]


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str: ...


def _format_feedback(concerns: list[str], suggestions: list[str]) -> str:
    """Format AI tool feedback into a text block for advisor injection."""
    parts = []
    if concerns:
        parts.append("**Concerns raised by the AI coding tool:**")
        for i, c in enumerate(concerns, 1):
            parts.append(f"  {i}. {c}")
    if suggestions:
        parts.append("\n**Suggestions from the AI coding tool:**")
        for i, s in enumerate(suggestions, 1):
            parts.append(f"  {i}. {s}")
    return "\n".join(parts)


async def negotiate_plan(
    plan: ChangePlan,
    state: PlanState,
    context: ProjectContext,
    concerns: list[str],
    suggestions: list[str],
    llm: LLMClient,
    settings: Settings,
) -> ChangePlan:
    """Run one round of negotiation.

    Args:
        plan: The current plan that was rejected.
        state: The plan's state (mutated in place).
        context: Project context.
        concerns: AI tool's specific concerns.
        suggestions: AI tool's alternative suggestions.
        llm: LLM client.
        settings: App settings.

    Returns:
        An updated ChangePlan incorporating the feedback.

    Side effects:
        - Mutates state: records the negotiation round, transitions
          back to DRAFTING then PROPOSED.
    """
    # Format feedback for advisor injection
    feedback_text = _format_feedback(concerns, suggestions)

    # Transition back to drafting for re-deliberation
    state.transition(PlanStatus.DRAFTING)

    # Re-run advisors with feedback
    advisor_responses, advisor_params, timing = await run_advisors(
        change_description=plan.change_description,
        context=context,
        llm=llm,
        plan_id=plan.plan_id,
        temperature_spread=settings.code_council_advisor_temperature_spread,
        negotiation_feedback=feedback_text,
    )

    # Re-synthesize plan
    updated_plan = await synthesize_plan(
        change_description=plan.change_description,
        advisor_responses=advisor_responses,
        context=context,
        plan_id=plan.plan_id,
        llm=llm,
        negotiation_round=state.negotiation_round + 1,
    )

    # Determine what changed between plans
    plan_changes = _diff_plans(plan, updated_plan)

    # Record the negotiation round
    state.record_negotiation(
        concerns=concerns,
        suggestions=suggestions,
        plan_changes=plan_changes,
    )

    # Transition back to proposed
    state.transition(PlanStatus.PROPOSED)

    logger.info(
        "Negotiation round %d complete for plan %s. Changes: %s",
        state.negotiation_round, plan.plan_id, plan_changes,
    )

    return updated_plan


def _diff_plans(old: ChangePlan, new: ChangePlan) -> list[str]:
    """Compute a human-readable diff between two plan versions.

    Returns a list of change descriptions.
    """
    changes: list[str] = []

    # Check affected files
    old_files = set(old.affected_files)
    new_files = set(new.affected_files)
    added = new_files - old_files
    removed = old_files - new_files
    if added:
        changes.append(f"Added files: {', '.join(sorted(added))}")
    if removed:
        changes.append(f"Removed files: {', '.join(sorted(removed))}")

    # Check step count
    if len(new.implementation_steps) != len(old.implementation_steps):
        changes.append(
            f"Steps changed: {len(old.implementation_steps)} -> "
            f"{len(new.implementation_steps)}"
        )

    # Check risk level
    if new.risk_level != old.risk_level:
        changes.append(f"Risk level changed: {old.risk_level} -> {new.risk_level}")

    # Check effort
    if new.estimated_effort != old.estimated_effort:
        changes.append(f"Effort changed: {old.estimated_effort} -> {new.estimated_effort}")

    if not changes:
        changes.append("Minor wording changes (no structural differences)")

    return changes
```

### Negotiation Flow Diagram

```
Round 0: Initial plan
  |
  v
AI tool calls review_plan(feasible=False, concerns=[...])
  |
  v
negotiate_plan():
  1. state: REVIEWING -> DRAFTING
  2. Re-run 5 advisors with concerns injected
  3. Re-synthesize plan
  4. Compute diff between old and new plan
  5. Record round in state.negotiation_history
  6. state: DRAFTING -> PROPOSED
  |
  v
Return updated plan to AI tool
  |
  v
AI tool reviews again...
  |
  +--- feasible? ---+
  |                  |
  v NO               v YES
  Round 2...         state: AGREED
  |
  v (if round > max_rounds)
  state: STALLED (needs human)
```

---

## 12. Module: cli.py

**File:** `code_council/cli.py`

The CLI provides two modes of operation:
1. `code-council serve` -- Start the MCP server (primary use case)
2. `code-council plan` -- Manual plan creation without MCP (fallback)

```python
"""CLI entry-point for code-council.

Installed as the `code-council` command via pyproject.toml.

Primary command:
    code-council serve     -- Start MCP server on STDIO (for AI tool integration)

Manual commands:
    code-council plan      -- Create a plan without MCP
    code-council plans     -- List recent plans
    code-council show      -- View a specific plan
    code-council export    -- Export a plan as markdown
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from code_council.config import get_settings

app = typer.Typer(
    name="code-council",
    help="Plan code changes through multi-advisor deliberation.",
    add_completion=False,
)


# ---------------------------------------------------------------------------
# serve -- MCP server
# ---------------------------------------------------------------------------


@app.command()
def serve() -> None:
    """Start the MCP server on STDIO transport.

    This is the primary command. AI coding tools (Cursor, Copilot, OpenCode)
    connect to this server via their MCP configuration.
    """
    from code_council.mcp_server import run_server

    run_server()


# ---------------------------------------------------------------------------
# plan -- manual plan creation
# ---------------------------------------------------------------------------


@app.command()
def plan(
    description: str = typer.Argument(
        ...,
        help="Description of the change to plan.",
    ),
    project: str = typer.Option(
        ".",
        "--project", "-p",
        help="Path to the project root.",
    ),
) -> None:
    """Create a plan without MCP (manual mode).

    Runs the full advisor council and outputs the plan to stdout.
    Useful for testing or for AI tools that do not support MCP.
    """
    from code_council.advisors import run_advisors
    from code_council.context import gather_context
    from code_council.llm import get_llm
    from code_council.state import PlanState
    from code_council.synthesizer import synthesize_plan

    import uuid

    settings = get_settings()
    settings.require_langdock()
    llm = get_llm(settings)
    plan_id = uuid.uuid4().hex[:12]

    typer.echo("Gathering project context...")
    context = asyncio.run(gather_context(project, description))

    typer.echo("Running 5 advisors in parallel...")
    advisor_responses, _, _ = asyncio.run(
        run_advisors(
            change_description=description,
            context=context,
            llm=llm,
            plan_id=plan_id,
            temperature_spread=settings.code_council_advisor_temperature_spread,
        )
    )

    typer.echo("Synthesizing plan...")
    result = asyncio.run(
        synthesize_plan(
            change_description=description,
            advisor_responses=advisor_responses,
            context=context,
            plan_id=plan_id,
            llm=llm,
        )
    )

    typer.echo()
    typer.echo(json.dumps(result.model_dump(), indent=2))


# ---------------------------------------------------------------------------
# plans -- list recent
# ---------------------------------------------------------------------------


@app.command()
def plans(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of plans to show."),
) -> None:
    """List recent plans."""
    from code_council.storage import list_recent_plans

    results = list_recent_plans(limit=limit)
    if not results:
        typer.echo("No plans found.")
        return

    for p in results:
        status = p.get("status", "?")
        risk = p.get("risk_level", "?")
        effort = p.get("effort", "?")
        desc = p.get("change_description", "")
        typer.echo(
            f"  {p['plan_id']}  [{status}]  "
            f"risk={risk} effort={effort}  "
            f"{desc}"
        )


# ---------------------------------------------------------------------------
# show -- view a plan
# ---------------------------------------------------------------------------


@app.command()
def show(
    plan_id: str = typer.Argument(..., help="Plan ID to display."),
) -> None:
    """View a specific plan."""
    from code_council.storage import load_plan

    data = load_plan(plan_id)
    if not data:
        typer.echo(f"Plan '{plan_id}' not found.", err=True)
        raise typer.Exit(code=1)

    typer.echo(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# export -- markdown export
# ---------------------------------------------------------------------------


@app.command()
def export(
    plan_id: str = typer.Argument(..., help="Plan ID to export."),
    output: str = typer.Option(
        None, "--output", "-o",
        help="Output file path. Defaults to stdout.",
    ),
) -> None:
    """Export a plan as a markdown file.

    Useful as a fallback for AI tools that do not support MCP.
    Copy the output into your AI tool's prompt.
    """
    from code_council.storage import load_plan

    data = load_plan(plan_id)
    if not data:
        typer.echo(f"Plan '{plan_id}' not found.", err=True)
        raise typer.Exit(code=1)

    plan_data = data.get("plan", {})
    md = _format_plan_markdown(plan_data)

    if output:
        Path(output).write_text(md)
        typer.echo(f"Plan exported to {output}")
    else:
        typer.echo(md)


def _format_plan_markdown(plan: dict) -> str:
    """Format plan dict as a markdown document."""
    steps = plan.get("implementation_steps", [])
    steps_text = "\n".join(
        f"{s['order']}. **[{s['action'].upper()}]** `{s['file_path']}`\n"
        f"   {s['description']}\n"
        for s in steps
    )
    criteria = "\n".join(
        f"- [ ] {c}" for c in plan.get("acceptance_criteria", [])
    )

    return (
        f"# {plan.get('title', 'Change Plan')}\n\n"
        f"**Risk:** {plan.get('risk_level', '?')} | "
        f"**Effort:** {plan.get('estimated_effort', '?')}\n\n"
        f"## Summary\n\n{plan.get('summary', '')}\n\n"
        f"## Affected Files\n\n"
        + "\n".join(f"- `{f}`" for f in plan.get("affected_files", []))
        + f"\n\n## Implementation Steps\n\n{steps_text}\n"
        f"## Architecture Notes\n\n{plan.get('architecture_notes', '')}\n\n"
        f"## Security Notes\n\n{plan.get('security_notes', '')}\n\n"
        f"## Quality & Tests\n\n{plan.get('quality_notes', '')}\n\n"
        f"## Risks\n\n{plan.get('risk_assessment', '')}\n\n"
        f"## Execution Strategy\n\n{plan.get('execution_strategy', '')}\n\n"
        f"## Acceptance Criteria\n\n{criteria}\n"
    )


if __name__ == "__main__":
    app()
```

---

## 13. Skill Files

These markdown files live in `code_council/skills/` and are loaded at
runtime by the advisors and synthesizer. They provide detailed instructions
for each role.

### skills/architect.md

```markdown
# Architect Advisor

You analyze proposed code changes for structural and architectural soundness.

## Your Focus Areas

1. **Module boundaries** -- Does this change respect existing module boundaries?
   Does it introduce cross-cutting concerns that should be isolated?

2. **Dependency direction** -- Do dependencies flow in the right direction?
   Are there circular dependencies being introduced?

3. **Coupling and cohesion** -- Does this increase coupling between modules
   that should be independent? Does it group related functionality together?

4. **Existing patterns** -- What patterns does this codebase already use?
   (Repository pattern, service layer, dependency injection, etc.)
   Does the proposed change follow them or introduce a new one?

5. **API surface** -- If this change affects public APIs (HTTP endpoints,
   exported functions, CLI commands), are the changes backward compatible?

## How to Analyze

- Reference SPECIFIC files and patterns from the project context.
- If you see a pattern in the codebase (e.g., all database access goes
  through a repository layer), flag any change that violates it.
- If the change introduces a new pattern, explicitly call it out and
  explain whether it should be adopted project-wide or is a one-off.
- Think about what happens at 10x scale. Will this architecture hold?

## Output Format

Structure your analysis as:
1. **Architectural fit** -- How well does this fit the existing architecture?
2. **Concerns** -- Specific structural problems you see.
3. **Recommendations** -- How to structure the change properly.
```

### skills/security.md

```markdown
# Security Advisor

You analyze proposed code changes for security implications.

## Your Focus Areas

1. **Input validation** -- Does the change handle untrusted input? Are there
   injection risks (SQL, XSS, command injection, path traversal)?

2. **Authentication & authorization** -- Does this change affect who can
   access what? Are there privilege escalation risks?

3. **Data exposure** -- Could this change leak sensitive data through logs,
   error messages, API responses, or debug output?

4. **Secrets management** -- Are API keys, passwords, or tokens handled
   securely? Are they hardcoded anywhere?

5. **Dependency risks** -- Does this change add new dependencies? Are they
   well-maintained and free of known vulnerabilities?

6. **OWASP Top 10** -- Does this change introduce any OWASP Top 10 risks?

## How to Analyze

- Be specific. Don't say "this might have security issues." Say exactly
  what the vulnerability is, how it could be exploited, and how to fix it.
- Reference the actual files and functions where the risk exists.
- If the change is security-neutral (e.g., a UI color change), say so
  briefly and don't manufacture concerns.

## Output Format

Structure your analysis as:
1. **Risk level** -- NONE / LOW / MEDIUM / HIGH / CRITICAL
2. **Findings** -- Specific security concerns with file/line references.
3. **Required mitigations** -- What must be done before this ships.
```

### skills/quality.md

```markdown
# Quality & Developer Experience Advisor

You analyze proposed code changes for maintainability, testability, and
developer experience.

## Your Focus Areas

1. **Testability** -- Can the proposed changes be unit tested? Integration
   tested? What test patterns does the project already use? What new tests
   are needed?

2. **Existing test impact** -- Which existing tests will break? Which need
   updating? List specific test files and test functions.

3. **Readability** -- Is the proposed change easy to understand? Does it
   follow the project's naming conventions? Are there magic numbers or
   unclear abstractions?

4. **Error handling** -- Does the change handle error cases? Does it follow
   the project's error handling patterns (exceptions, Result types, error
   codes)?

5. **Documentation** -- Does this change need documentation updates?
   Docstrings? README changes? API docs?

6. **Code style** -- Does it match the project's style (linting rules,
   formatting conventions)?

## How to Analyze

- Look at the existing test files in the project context. Match their
  patterns when suggesting new tests.
- If the project uses a FakeLLM or mock pattern for testing, suggest
  tests that follow the same approach.
- Be specific about which test files need changes and what test cases
  to add.

## Output Format

Structure your analysis as:
1. **Tests to update** -- Existing tests that will break or need changes.
2. **Tests to add** -- New test cases needed, with specific descriptions.
3. **Quality concerns** -- Readability, naming, error handling issues.
4. **Documentation needs** -- What docs need updating.
```

### skills/risk.md

```markdown
# Risk Advisor

You analyze proposed code changes for what could go wrong.

## Your Focus Areas

1. **Breaking changes** -- Does this change break any public API, CLI
   command, configuration format, or data schema? List exactly what breaks.

2. **Backward compatibility** -- Can existing users/callers continue to
   work without changes? If not, what migration is needed?

3. **Data migration** -- Does this change the shape of stored data
   (database schemas, JSON files, config formats)? What happens to
   existing data?

4. **Rollback strategy** -- If this change causes problems in production,
   can it be safely rolled back? Or is it a one-way door?

5. **Performance regression** -- Could this change make things slower?
   More memory? More API calls? More disk I/O?

6. **Blast radius** -- How many parts of the system are affected? Is this
   a surgical change or does it touch everything?

## How to Analyze

- Assign a risk level: LOW / MEDIUM / HIGH.
- LOW: Self-contained change, easy to roll back, no data migration.
- MEDIUM: Touches multiple modules, some tests need updating, minor
  migration needed.
- HIGH: Breaking API changes, data migration required, hard to roll back,
  or touches critical paths.
- Be honest. If the risk is low, say so. Don't inflate risk to seem thorough.

## Output Format

Structure your analysis as:
1. **Risk level** -- LOW / MEDIUM / HIGH with one-sentence justification.
2. **What could break** -- Specific failure scenarios.
3. **Mitigations** -- How to reduce each risk.
4. **Rollback plan** -- How to undo this change if needed.
```

### skills/executor.md

```markdown
# Executor Advisor

You focus exclusively on HOW to implement the change. You are the most
concrete and practical advisor.

## Your Focus Areas

1. **File change sequence** -- Which files need to change, in what order?
   Dependencies between changes matter: don't modify a caller before the
   callee is updated.

2. **Incremental delivery** -- Can this be split into multiple smaller
   changes (PRs/commits)? If the change touches 5+ files, suggest a
   phased approach where each phase is independently deployable/testable.

3. **Effort estimate** -- How big is this?
   - S: < 1 hour, 1-2 files
   - M: 1-4 hours, 3-5 files
   - L: 4-8 hours, 5-10 files
   - XL: 1+ days, 10+ files or requires research

4. **First concrete step** -- What is the literal first thing to do?
   Not "understand the requirements." Something like "create file X
   with class Y that implements interface Z."

5. **Verification** -- After each step, how do you verify it worked?
   Which command to run, which test to check.

## How to Analyze

- Be extremely specific. "Modify the auth module" is too vague.
  "Add a `verify_jwt()` function to `src/auth/tokens.py` that takes
  a token string and returns a `UserClaims` dataclass" is the right level.
- Reference actual file paths from the project context.
- Think about the developer's workflow: edit, run tests, verify, commit.

## Output Format

Structure your analysis as:
1. **Effort estimate** -- S / M / L / XL
2. **Recommended sequence** -- Ordered list of file changes.
3. **Phasing** -- Can this be split? How?
4. **First step** -- The literal first action.
5. **Verification** -- How to verify each step.
```

### skills/synthesizer.md

```markdown
# Plan Synthesizer

You take the analyses from 5 code advisors and produce a single, structured
implementation plan. You are not an advisor -- you are the decision-maker.

## Your Role

The 5 advisors (Architect, Security, Quality, Risk, Executor) have each
analyzed the proposed change from their perspective. They will disagree.
Your job is to:

1. **Resolve conflicts** -- When advisors disagree, make a judgment call.
   Note the trade-off in the plan.
2. **Merge insights** -- Combine the best elements from each advisor.
3. **Produce actionable steps** -- Not high-level guidance. Specific,
   ordered, file-level implementation steps.
4. **Set realistic expectations** -- Risk level and effort estimate must
   reflect reality, not optimism.

## Rules

- Every file in `implementation_steps` MUST appear in `affected_files`.
- Steps MUST be ordered by dependency (if step 3 depends on step 1,
  `depends_on` must say so).
- Acceptance criteria MUST be verifiable (not "code is clean" but
  "all tests pass" or "endpoint returns 200 for valid JWT").
- If Security flags a CRITICAL risk, it MUST be addressed in the plan
  as a prerequisite step, not a follow-up.
- Use the Executor's sequencing as the starting point but adjust based
  on Architect and Security input.
- If Risk says HIGH, the plan must include a rollback strategy step.

## Output

Output a JSON object matching the ChangePlan schema exactly. Do not
add commentary outside the JSON block.
```

---

## 14. Testing Strategy

All tests use a `FakeLLM` -- **no test ever calls Langdock**. This is the
same pattern used in council-me's test suite.

### FakeLLM

```python
"""Shared test fixtures for code-council tests.

Place this in tests/conftest.py or import directly.
"""

from __future__ import annotations

from typing import Any

from code_council.advisors import ADVISORS
from code_council.context import ProjectContext, TechStack, TestPatterns
from code_council.llm import LLMResult, TokenUsage


# ---------------------------------------------------------------------------
# FakeLLM
# ---------------------------------------------------------------------------


class FakeLLM:
    """Deterministic LLM stub that returns canned responses based on prompt content.

    Implements both the basic API (complete/chat returning str) and the
    extended API (complete_with_usage/chat_with_usage returning LLMResult)
    to match LangdockLLM post-0.10.0.
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []
        self.call_params: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        self.call_params.append({
            "prompt_preview": prompt[:80],
            "temperature": temperature,
            "seed": seed,
        })

        # Synthesizer prompt -- return valid JSON plan
        if "Plan Synthesizer" in prompt or "implementation_steps" in prompt:
            return '''```json
{
    "title": "Test Change",
    "summary": "A test change for unit testing.",
    "affected_files": ["src/main.py", "tests/test_main.py"],
    "implementation_steps": [
        {
            "order": 1,
            "file_path": "src/main.py",
            "action": "modify",
            "description": "Add the new function.",
            "depends_on": []
        },
        {
            "order": 2,
            "file_path": "tests/test_main.py",
            "action": "modify",
            "description": "Add tests for the new function.",
            "depends_on": [1]
        }
    ],
    "architecture_notes": "Fits existing patterns.",
    "security_notes": "No security concerns.",
    "quality_notes": "Add unit tests.",
    "risk_assessment": "Low risk, self-contained change.",
    "execution_strategy": "Single PR, straightforward.",
    "acceptance_criteria": [
        "All existing tests pass",
        "New unit tests added"
    ],
    "estimated_effort": "S",
    "risk_level": "LOW"
}
```'''

        # Advisor responses -- echo back the role
        for role in ADVISORS:
            if f"You are the {role}" in prompt:
                return f"[{role} Advisor] Analysis of the proposed change."

        return "Generic LLM response."

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> str:
        self.call_count += 1
        return "Chat response."

    # -- Extended API (token usage) ----------------------------------------

    async def complete_with_usage(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        text = await self.complete(prompt, temperature=temperature, seed=seed)
        return LLMResult(
            text=text,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )

    async def chat_with_usage(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> LLMResult:
        text = await self.chat(messages, temperature=temperature, seed=seed)
        return LLMResult(
            text=text,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )


# ---------------------------------------------------------------------------
# Fake ProjectContext
# ---------------------------------------------------------------------------


def fake_context(project_path: str = "/tmp/test-project") -> ProjectContext:
    """Create a minimal ProjectContext for testing."""
    return ProjectContext(
        project_path=project_path,
        directory_tree="src/\n  main.py\n  utils.py\ntests/\n  test_main.py",
        tech_stack=TechStack(
            languages=["Python"],
            frameworks=["FastAPI"],
            build_tools=["hatchling"],
            package_manager="pip",
            runtime="python3.11",
        ),
        config_files={"pyproject.toml": '[project]\nname = "test"'},
        relevant_files={"src/main.py": "def hello():\n    return 'world'"},
        test_patterns=TestPatterns(
            test_framework="pytest",
            test_directories=["tests/"],
            test_file_pattern="test_*.py",
            example_test_files=["tests/test_main.py"],
        ),
        summary="A simple Python FastAPI project.",
    )
```

### Test Files

#### tests/test_config.py

```python
"""Tests for code_council.config."""

import os
from pathlib import Path
from unittest import mock

import pytest

from code_council.config import Settings, _load_env_file


class TestSettings:
    def test_defaults(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.code_council_max_negotiation_rounds == 3
        assert s.code_council_save_plans is True
        assert s.code_council_advisor_temperature_spread == 0.4

    def test_env_override(self) -> None:
        env = {
            "LANGDOCK_API_KEY": "test-key",
            "LANGDOCK_BASE_URL": "https://test.example.com/v1",
            "CODE_COUNCIL_MODEL": "test-model",
            "CODE_COUNCIL_MAX_NEGOTIATION_ROUNDS": "5",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            s = Settings()
        assert s.langdock_api_key == "test-key"
        assert s.code_council_model == "test-model"
        assert s.code_council_max_negotiation_rounds == 5

    def test_require_langdock_raises_when_missing(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            s = Settings()
        with pytest.raises(EnvironmentError, match="LANGDOCK_API_KEY"):
            s.require_langdock()

    def test_plan_path(self) -> None:
        with mock.patch.dict(os.environ, {"CODE_COUNCIL_PLAN_DIR": "/tmp/plans"}, clear=True):
            s = Settings()
        assert s.plan_path == Path("/tmp/plans")


class TestLoadEnvFile:
    def test_loads_values(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("TEST_CC_VAR=hello\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_CC_VAR", None)
            _load_env_file(env_file)
            assert os.environ["TEST_CC_VAR"] == "hello"
            del os.environ["TEST_CC_VAR"]

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("TEST_CC_VAR=from_file\n")
        with mock.patch.dict(os.environ, {"TEST_CC_VAR": "from_shell"}, clear=False):
            _load_env_file(env_file)
            assert os.environ["TEST_CC_VAR"] == "from_shell"

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        _load_env_file(tmp_path / "nonexistent")  # should not raise
```

#### tests/test_context.py

```python
"""Tests for code_council.context -- filesystem scanning."""

import pytest
from pathlib import Path

from code_council.context import (
    build_directory_tree,
    detect_tech_stack,
    find_config_files,
    detect_test_patterns,
    find_relevant_files,
    gather_context,
    IGNORED_DIRS,
)


class TestDirectoryTree:
    def test_builds_tree_from_simple_project(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")

        tree = build_directory_tree(tmp_path)
        assert "src" in tree
        assert "main.py" in tree
        assert "tests" in tree

    def test_ignores_git_and_node_modules(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x")

        tree = build_directory_tree(tmp_path)
        assert ".git" not in tree
        assert "node_modules" not in tree
        assert "src" in tree


class TestTechStackDetection:
    def test_detects_python_project(self, tmp_path: Path) -> None:
        config = {"pyproject.toml": '[project]\nname="myapp"\ndependencies=["fastapi"]'}
        tech = detect_tech_stack(tmp_path, config)
        assert "Python" in tech.languages
        assert "FastAPI" in [f.lower() for f in tech.frameworks] or "fastapi" in str(tech.frameworks).lower()

    def test_detects_node_project(self, tmp_path: Path) -> None:
        config = {"package.json": '{"dependencies": {"react": "^18"}}'}
        tech = detect_tech_stack(tmp_path, config)
        assert "JavaScript" in tech.languages or "TypeScript" in tech.languages


class TestFindRelevantFiles:
    def test_finds_files_matching_keywords(self, tmp_path: Path) -> None:
        (tmp_path / "auth.py").write_text("def login(): pass")
        (tmp_path / "utils.py").write_text("def helper(): pass")
        (tmp_path / "auth_test.py").write_text("def test_login(): pass")

        relevant = find_relevant_files(tmp_path, "add authentication login")
        # auth.py and auth_test.py should score higher than utils.py
        assert "auth.py" in " ".join(relevant.keys()) or any("auth" in k for k in relevant.keys())


@pytest.mark.asyncio
async def test_gather_context_returns_complete_object(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")

    ctx = await gather_context(str(tmp_path), "add a feature")
    assert ctx.project_path == str(tmp_path)
    assert ctx.directory_tree != ""
    assert "pyproject.toml" in ctx.config_files
    assert ctx.tech_stack.languages  # should detect at least one language
```

#### tests/test_advisors.py

```python
"""Tests for code_council.advisors -- advisor execution and diversity."""

import os
from unittest import mock

import pytest

from code_council.advisors import (
    ADVISORS,
    ADVISOR_DIVERSITY,
    _advisor_temperature,
    _advisor_seed,
    run_advisors,
)

# Import shared fixtures
from tests.conftest import FakeLLM, fake_context


class TestDiversityControls:
    def test_temperatures_are_distinct(self) -> None:
        spread = 0.4
        temps = {name: _advisor_temperature(name, spread) for name in ADVISORS}
        assert len(set(temps.values())) == 5
        assert min(temps.values()) == pytest.approx(0.6)
        assert max(temps.values()) == pytest.approx(1.0)

    def test_zero_spread_returns_default(self) -> None:
        for name in ADVISORS:
            assert _advisor_temperature(name, 0.0) == 1.0

    def test_seeds_are_deterministic(self) -> None:
        seeds_a = {name: _advisor_seed(name, "abc") for name in ADVISORS}
        seeds_b = {name: _advisor_seed(name, "abc") for name in ADVISORS}
        assert seeds_a == seeds_b

    def test_seeds_differ_per_advisor(self) -> None:
        seeds = {name: _advisor_seed(name, "test") for name in ADVISORS}
        assert len(set(seeds.values())) == 5


@pytest.mark.asyncio
async def test_run_advisors_returns_all_five() -> None:
    llm = FakeLLM()
    ctx = fake_context()
    responses, params, timing = await run_advisors(
        change_description="Add authentication",
        context=ctx,
        llm=llm,
        plan_id="test123",
    )
    assert len(responses) == 5
    for name in ADVISORS:
        assert name in responses
    assert len(params) == 5
    assert timing["duration"] >= 0


@pytest.mark.asyncio
async def test_advisors_receive_distinct_params() -> None:
    llm = FakeLLM()
    ctx = fake_context()
    _, params, _ = await run_advisors(
        change_description="Test",
        context=ctx,
        llm=llm,
        plan_id="test456",
    )
    temps = {p["temperature"] for p in params.values()}
    seeds = {p["seed"] for p in params.values()}
    assert len(temps) == 5
    assert len(seeds) == 5


@pytest.mark.asyncio
async def test_negotiation_feedback_injected() -> None:
    llm = FakeLLM()
    ctx = fake_context()
    await run_advisors(
        change_description="Test",
        context=ctx,
        llm=llm,
        plan_id="test789",
        negotiation_feedback="The auth module does not exist yet.",
    )
    # Check that feedback appears in at least one prompt
    assert any("auth module does not exist" in p for p in llm.prompts)
```

#### tests/test_synthesizer.py

```python
"""Tests for code_council.synthesizer -- plan synthesis."""

import pytest

from code_council.synthesizer import synthesize_plan, ChangePlan, _extract_json
from tests.conftest import FakeLLM, fake_context


class TestExtractJson:
    def test_extracts_from_code_fence(self) -> None:
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        assert _extract_json(text) == '{"key": "value"}'

    def test_handles_raw_json(self) -> None:
        text = '{"key": "value"}'
        assert _extract_json(text) == '{"key": "value"}'


@pytest.mark.asyncio
async def test_synthesize_produces_valid_plan() -> None:
    llm = FakeLLM()
    ctx = fake_context()
    plan = await synthesize_plan(
        change_description="Add a feature",
        advisor_responses={
            "Architect": "Fits well.",
            "Security": "No issues.",
            "Quality": "Add tests.",
            "Risk": "Low risk.",
            "Executor": "Start with main.py.",
        },
        context=ctx,
        plan_id="synth-test",
        llm=llm,
    )
    assert isinstance(plan, ChangePlan)
    assert plan.plan_id == "synth-test"
    assert len(plan.affected_files) > 0
    assert len(plan.implementation_steps) > 0
    assert plan.risk_level in ("LOW", "MEDIUM", "HIGH")
    assert plan.estimated_effort in ("S", "M", "L", "XL")
```

#### tests/test_state.py

```python
"""Tests for code_council.state -- plan state machine."""

import pytest

from code_council.state import PlanState, PlanStatus


class TestPlanState:
    def test_initial_state_is_drafting(self) -> None:
        state = PlanState(plan_id="test")
        assert state.status == PlanStatus.DRAFTING

    def test_valid_transition(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.PROPOSED)
        assert state.status == PlanStatus.PROPOSED

    def test_invalid_transition_raises(self) -> None:
        state = PlanState(plan_id="test")
        with pytest.raises(ValueError, match="Invalid transition"):
            state.transition(PlanStatus.AGREED)  # can't go DRAFTING -> AGREED

    def test_full_happy_path(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        state.transition(PlanStatus.AGREED)
        state.transition(PlanStatus.EXECUTING)
        state.transition(PlanStatus.COMPLETED)
        assert state.status == PlanStatus.COMPLETED

    def test_negotiation_loop(self) -> None:
        state = PlanState(plan_id="test", max_rounds=2)
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        # Rejected -- go back to drafting
        state.transition(PlanStatus.DRAFTING)
        assert state.can_negotiate()

        state.record_negotiation(["concern"], ["suggestion"], ["changed X"])
        assert state.negotiation_round == 1
        assert len(state.negotiation_history) == 1

    def test_max_rounds_exhausted(self) -> None:
        state = PlanState(plan_id="test", max_rounds=1)
        state.record_negotiation(["c"], ["s"], ["p"])
        assert not state.can_negotiate()

    def test_stalled_can_restart(self) -> None:
        state = PlanState(plan_id="test")
        state.transition(PlanStatus.PROPOSED)
        state.transition(PlanStatus.REVIEWING)
        state.transition(PlanStatus.STALLED)
        # Can restart from stalled
        state.transition(PlanStatus.DRAFTING)
        assert state.status == PlanStatus.DRAFTING
```

#### tests/test_storage.py

```python
"""Tests for code_council.storage -- plan persistence."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from code_council.config import Settings
from code_council.storage import save_plan, load_plan, list_recent_plans, delete_plan


class TestSavePlan:
    def test_saves_plan_to_disk(self, tmp_path: Path) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_save_plans = True
            settings.code_council_plan_dir = str(tmp_path)

        path = save_plan(
            plan_id="test-plan-1",
            change_description="Add auth",
            plan_data={"title": "Add Auth"},
            state_data={"status": "proposed"},
            advisor_responses={"Architect": "Looks good."},
            context_summary="Python FastAPI project.",
            settings=settings,
        )

        assert path is not None
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data["plan_id"] == "test-plan-1"
        assert data["change_description"] == "Add auth"

    def test_disabled_returns_none(self, tmp_path: Path) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_save_plans = False

        result = save_plan(
            plan_id="x", change_description="y",
            plan_data={}, state_data={},
            advisor_responses={}, context_summary="",
            settings=settings,
        )
        assert result is None


class TestLoadPlan:
    def test_loads_existing_plan(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan-abc.json"
        plan_file.write_text(json.dumps({"plan_id": "abc", "title": "Test"}))
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_plan_dir = str(tmp_path)
        data = load_plan("abc", settings=settings)
        assert data is not None
        assert data["plan_id"] == "abc"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_plan_dir = str(tmp_path)
        assert load_plan("nonexistent", settings=settings) is None


class TestListRecentPlans:
    def test_lists_plans_sorted_by_mtime(self, tmp_path: Path) -> None:
        for i in range(3):
            (tmp_path / f"plan-{i}.json").write_text(
                json.dumps({
                    "plan_id": str(i),
                    "change_description": f"Change {i}",
                    "state": {"status": "proposed"},
                    "plan": {"risk_level": "LOW", "estimated_effort": "S"},
                })
            )
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_plan_dir = str(tmp_path)
        results = list_recent_plans(limit=10, settings=settings)
        assert len(results) == 3


class TestDeletePlan:
    def test_deletes_existing(self, tmp_path: Path) -> None:
        (tmp_path / "plan-del.json").write_text("{}")
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_plan_dir = str(tmp_path)
        assert delete_plan("del", settings=settings) is True
        assert not (tmp_path / "plan-del.json").exists()

    def test_returns_false_for_missing(self, tmp_path: Path) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = Settings()
            settings.code_council_plan_dir = str(tmp_path)
        assert delete_plan("nope", settings=settings) is False
```

#### tests/test_negotiation.py

```python
"""Tests for code_council.negotiation -- feasibility negotiation loop."""

import pytest

from code_council.negotiation import negotiate_plan, _diff_plans, _format_feedback
from code_council.state import PlanState, PlanStatus
from code_council.synthesizer import ChangePlan, ImplementationStep
from tests.conftest import FakeLLM, fake_context


def _make_plan(plan_id: str = "neg-test", **overrides) -> ChangePlan:
    """Create a minimal ChangePlan for testing."""
    defaults = dict(
        plan_id=plan_id,
        title="Test Plan",
        summary="A test plan.",
        change_description="Add a feature.",
        affected_files=["src/main.py"],
        implementation_steps=[
            ImplementationStep(
                order=1, file_path="src/main.py",
                action="modify", description="Change it.",
                depends_on=[],
            )
        ],
        architecture_notes="OK",
        security_notes="OK",
        quality_notes="OK",
        risk_assessment="Low",
        execution_strategy="Just do it",
        acceptance_criteria=["Tests pass"],
        estimated_effort="S",
        risk_level="LOW",
    )
    defaults.update(overrides)
    return ChangePlan(**defaults)


class TestFormatFeedback:
    def test_formats_concerns_and_suggestions(self) -> None:
        text = _format_feedback(["File X doesn't exist"], ["Use Y instead"])
        assert "File X doesn't exist" in text
        assert "Use Y instead" in text

    def test_empty_feedback(self) -> None:
        text = _format_feedback([], [])
        assert text == ""  # or minimal output


class TestDiffPlans:
    def test_detects_added_files(self) -> None:
        old = _make_plan(affected_files=["a.py"])
        new = _make_plan(affected_files=["a.py", "b.py"])
        diff = _diff_plans(old, new)
        assert any("b.py" in d for d in diff)

    def test_detects_risk_change(self) -> None:
        old = _make_plan(risk_level="LOW")
        new = _make_plan(risk_level="HIGH")
        diff = _diff_plans(old, new)
        assert any("LOW" in d and "HIGH" in d for d in diff)


@pytest.mark.asyncio
async def test_negotiate_plan_produces_updated_plan() -> None:
    llm = FakeLLM()
    ctx = fake_context()
    plan = _make_plan()
    state = PlanState(plan_id="neg-test", max_rounds=3)
    state.transition(PlanStatus.PROPOSED)
    state.transition(PlanStatus.REVIEWING)

    updated = await negotiate_plan(
        plan=plan,
        state=state,
        context=ctx,
        concerns=["The file src/auth.py doesn't exist"],
        suggestions=["Create it first"],
        llm=llm,
        settings=None,  # will use get_settings()
    )

    assert isinstance(updated, ChangePlan)
    assert state.negotiation_round == 1
    assert state.status == PlanStatus.PROPOSED
    assert len(state.negotiation_history) == 1
```

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_advisors.py

# Run with coverage
pytest --cov=code_council
```

---

## 15. AI Tool Configuration and Build Order

### AI Tool Configuration

#### OpenCode

Add to your project's `opencode.json` or `opencode.jsonc`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "code-council": {
      "type": "local",
      "command": ["uv", "--directory", "/path/to/code-council", "run", "code-council", "serve"],
      "enabled": true
    }
  }
}
```

Or if installed globally:

```json
{
  "mcp": {
    "code-council": {
      "type": "local",
      "command": ["code-council", "serve"],
      "enabled": true
    }
  }
}
```

#### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "code-council": {
      "command": "uv",
      "args": ["--directory", "/path/to/code-council", "run", "code-council", "serve"]
    }
  }
}
```

#### GitHub Copilot (VS Code)

Add to `.vscode/mcp.json` in your project root:

```json
{
  "servers": {
    "code-council": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/path/to/code-council", "run", "code-council", "serve"]
    }
  }
}
```

#### Any Future MCP-Compatible Tool

The same pattern applies: point the tool at `code-council serve` via STDIO.
No code changes needed in Code Council itself.

### Usage Examples

Once configured, you can use Code Council from within your AI tool:

```
# Plan a change
Plan adding JWT authentication to the REST API using code-council

# After receiving the plan, the AI tool will automatically call
# review_plan to submit its feasibility assessment

# If agreed, execute
Execute the code-council plan
```

Or explicitly:

```
Use the code-council tool to plan adding a caching layer to the database queries.
Review the plan against the actual codebase. If anything looks wrong, submit
your concerns back to code-council. Once we agree, execute the plan.
```

### Build Order

Build the modules in this order. Each phase is independently testable.

#### Phase 1: Foundation (no LLM calls)
| Order | File | Test File | What to Verify |
|---|---|---|---|
| 1 | `pyproject.toml` | -- | `pip install -e ".[dev]"` succeeds |
| 2 | `code_council/__init__.py` | -- | Package imports |
| 3 | `code_council/config.py` | `tests/test_config.py` | `pytest tests/test_config.py` passes |
| 4 | `code_council/state.py` | `tests/test_state.py` | `pytest tests/test_state.py` passes |
| 5 | `code_council/storage.py` | `tests/test_storage.py` | `pytest tests/test_storage.py` passes |

#### Phase 2: Context Gathering (no LLM calls)
| Order | File | Test File | What to Verify |
|---|---|---|---|
| 6 | `code_council/context.py` | `tests/test_context.py` | `pytest tests/test_context.py` passes |

#### Phase 3: LLM Layer (FakeLLM only)
| Order | File | Test File | What to Verify |
|---|---|---|---|
| 7 | `code_council/llm.py` | -- | Imports work (real test needs Langdock) |
| 8 | Skill files (`skills/*.md`) | -- | Files exist and are readable |

#### Phase 4: Core Pipeline (FakeLLM)
| Order | File | Test File | What to Verify |
|---|---|---|---|
| 9 | `code_council/advisors.py` | `tests/test_advisors.py` | `pytest tests/test_advisors.py` passes |
| 10 | `code_council/synthesizer.py` | `tests/test_synthesizer.py` | `pytest tests/test_synthesizer.py` passes |
| 11 | `code_council/negotiation.py` | `tests/test_negotiation.py` | `pytest tests/test_negotiation.py` passes |

#### Phase 5: Integration (MCP + CLI)
| Order | File | Test File | What to Verify |
|---|---|---|---|
| 12 | `code_council/mcp_server.py` | `tests/test_mcp_server.py` | `pytest tests/test_mcp_server.py` passes |
| 13 | `code_council/cli.py` | -- | `code-council --help` works |

#### Phase 6: End-to-End Verification
| Step | Command | Expected |
|---|---|---|
| 1 | `pytest` | All tests pass |
| 2 | `ruff check code_council/` | No lint errors |
| 3 | `code-council serve` | MCP server starts on STDIO |
| 4 | Configure in OpenCode/Cursor | Tool appears in MCP tool list |
| 5 | `plan adding a health check endpoint` | Plan is generated and returned |

### Total File Count

| Category | Count |
|---|---|
| Python source files | 10 |
| Skill markdown files | 6 |
| Test files | 7 |
| Config files (pyproject.toml, etc.) | 2 |
| **Total** | **25** |

### Total LLM Calls Per Plan

| Phase | Calls |
|---|---|
| Context gathering | 0 (filesystem only) |
| 5 advisors (parallel) | 5 |
| 1 synthesizer | 1 |
| **First pass total** | **6** |
| Each negotiation round | 6 |
| Typical total (1 round) | 12 |
| Maximum total (3 rounds) | 24 |

---

## Summary

Code Council is a 25-file Python project that:

1. Scans a target project's filesystem for context
2. Runs 5 code-focused advisors in parallel (Architect, Security, Quality, Risk, Executor)
3. Synthesizes a structured implementation plan
4. Exposes the plan via MCP for AI coding tools to review and negotiate
5. Iterates until the council and AI tool agree
6. Hands off step-by-step implementation instructions

It connects to Cursor, GitHub Copilot, and OpenCode via MCP (STDIO transport)
with zero code changes when adding new tools. All LLM calls go through
Langdock. All tests use FakeLLM and never touch the network.

Build it in 6 phases, test each phase independently, and the whole thing
works end-to-end once Phase 5 is complete.
