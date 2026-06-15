# Code Council -- Project Context

> This document is the single source of truth for understanding the Code Council
> codebase. Keep it in sync with the code whenever modules, commands, or
> architecture change.
>
> **Before making changes:** Check this file and `docs/code-council-plan.md` for
> the current architecture and original design intent.
> **After making changes:** Update this file, `README.md`, and `AGENTS.md` to
> reflect the new state. Run `pytest` to verify nothing is broken.
>
> **Note on `docs/code-council-plan.md`:** The original design document references
> "5 advisors" throughout. The codebase now has 6 (Business Advisor was added
> after the design doc was written). Treat this file as the current source of
> truth and the design doc as a historical reference.

## Overview

**Code Council** (repo codename: *zangetsu*) is a Python CLI tool that produces
structured implementation plans for code changes through **multi-advisor
deliberation** -- before any code is written.

The CLI command is `bankai`. A developer describes a feature or change in plain
English; Code Council frames it as structured requirements, runs 6 independent
advisors in parallel, and synthesizes a single actionable plan. The plan is then
copied into an AI coding agent (OpenCode, Cursor, GitHub Copilot) for execution.

- **Version:** 0.1.0
- **License:** MIT
- **Python:** >= 3.11
- **Build system:** Hatchling

---

## Directory Structure

```
zangetsu/
├── AGENTS.md                        # AI agent instructions (for OpenCode/Cursor/Copilot)
├── CONTEXT.md                       # This file -- full project context
├── README.md                        # Project overview and setup instructions
├── pyproject.toml                   # Build config, dependencies, CLI entry points
├── docs/
│   └── code-council-plan.md         # Full design document / implementation plan (~4100 lines)
├── code_council/                    # Main Python package
│   ├── __init__.py                  # Package init, __version__ = "0.1.0"
│   ├── cli.py                      # Typer CLI entry point (bankai command + subcommands + serve)
│   ├── daemon.py                   # FastAPI server for web UI (WS framer with transcript persistence, SSE pipeline, REST)
│   ├── utils.py                    # Shared utilities (generate_plan_id, slugify, plan_filename_stem)
│   ├── config.py                   # Settings via pydantic-settings + env file loader
│   ├── llm.py                      # Langdock/OpenAI LLM wrapper with retry logic
│   ├── context.py                  # Project filesystem scanner for advisor context
│   ├── framer.py                   # Requirements framing (Phase 1 of pipeline)
│   ├── advisors.py                 # Advisor skill registry + parallel execution engine
│   ├── synthesizer.py              # Plan synthesis from advisor outputs (Phase 4)
│   ├── state.py                    # Plan state machine (9 states, transition rules)
│   ├── storage.py                  # JSON plan persistence (save/load/list/delete)
│   ├── transcript.py              # Session transcript storage (framer Q&A log)
│   └── skills/                     # Self-describing advisor skill files (Markdown + YAML frontmatter)
│       ├── framer.md               # Requirements Framer skill definition
│       ├── executor.md             # Executor Advisor -- TDD, integration tests, test pyramid, coverage
│       ├── security.md             # Security Advisor -- vulnerabilities, auth, data exposure
│       ├── quality.md              # Quality & DX Advisor -- self-documenting code, tests as documentation
│       ├── business.md             # Business & Impact Advisor -- value, scope, tough questions
│       ├── architect.md            # Architect Advisor -- structure, patterns, coupling
│       ├── risk.md                 # Risk Advisor -- what could break, rollback, blast radius
│       └── synthesizer.md          # Plan Synthesizer -- merges all advisor outputs, enforces quality principles
├── web/                             # React + TypeScript web UI (Vite + Tailwind)
│   ├── package.json                 # Dependencies: react, react-markdown, tailwindcss
│   ├── vite.config.ts               # Dev server (port 5176), proxy to API (port 8766)
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx                 # React entry point
│       ├── App.tsx                  # Root component -- 6-phase wizard orchestrator
│       ├── index.css                # Tailwind + custom theme (system light/dark) + scroll-on-hover utility
│       ├── types.ts                 # Shared types mirroring Python models
│       ├── hooks/
│       │   ├── useFramer.ts         # WebSocket hook for framer interview
│       │   ├── useCouncilStream.ts  # SSE hook for advisor + synthesis pipeline
│       │   ├── useProjectScan.ts    # REST hook for project scanning flow
│       │   └── useRoute.ts          # Minimal History API router (/ and /history only)
│       └── components/
│           ├── DescriptionInput.tsx  # Step 1: feature description input + transcript loader
│           ├── FramerWizard.tsx      # Step 2: full-height chat-style framer Q&A
│           ├── RequirementReview.tsx # Step 3: framed requirement review/correct
│           ├── ProjectScanner.tsx    # Step 4: project scan + file approval
│           ├── AdvisorsPanel.tsx     # Step 5: advisor response grid
│           ├── AdvisorCard.tsx       # Individual expandable advisor card
│           ├── PipelineTracker.tsx   # Race-track progress bar (inline in header)
│           ├── PlanView.tsx          # Step 6: synthesized plan (tabbed layout, sticky footer)
│           ├── PlanHistory.tsx       # Plan list / history view (detail via component state)
│           ├── ErrorDisplay.tsx      # Reusable error component (retry/dismiss, compact variant)
│           └── MarkdownContent.tsx   # react-markdown wrapper
└── tests/                          # Test suite (pytest + pytest-asyncio)
    ├── __init__.py
    ├── conftest.py                 # Shared fixtures: FakeLLM, fake_context
    ├── test_config.py              # Settings defaults, env overrides, require_langdock
    ├── test_llm.py                 # TokenUsage, LLMResult, FakeLLM
    ├── test_skill_registry.py      # Frontmatter parsing, skill discovery, temperature/seed math
    ├── test_skill_model_routing.py # Per-skill model override field
    ├── test_context_scanning.py    # Directory tree, tech detection, config files
    ├── test_context_gather.py      # gather_context integration
    ├── test_context_approval.py    # Dotfile detection, credential detection, file safety
    ├── test_framer.py              # FramedRequirement model, frame_request end-to-end
    ├── test_synthesizer.py         # synthesize_plan, JSON extraction
    ├── test_storage.py             # Save/load/list/delete plans
    ├── test_state_status.py        # PlanStatus enum values
    ├── test_state_transitions.py   # State machine valid/invalid transitions
    ├── test_state_negotiation.py   # Negotiation round tracking
    ├── test_transcript.py          # Transcript init, append, load, full flow
    └── test_review_init.py         # Re-advise review init, transcript + base_plan_id
```

---

## Pipeline Architecture

The `bankai` command runs a 5-phase pipeline with a review loop after synthesis:

```
User runs: bankai "Add user authentication"
                    │
                    ▼
         ┌──────────────────┐
         │ INIT TRANSCRIPT  │  transcript.py creates transcript file
         │ (transcript.py)  │  Records original question
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
Phase 1  │     FRAMING      │  frame_request() calls LLM with framer.md skill
         │  (framer.py)     │  Produces FramedRequirement (Jira-style)
         └────────┬─────────┘
                  │  If needs_clarification(): ask questions one by one, loop
                  │  Each Q&A pair is appended to the transcript
                  ▼
         ┌──────────────────┐
Phase 2  │  PROJECT CONTEXT │  Interactive: scan filesystem, approve files
         │  (context.py)    │  Produces ProjectContext (tree, tech stack, files)
         └────────┬─────────┘
                  ▼
    ┌─────────────────────────────────────┐
    │  Phase 3 & 4 (review loop)         │
    │                                     │
    │  ┌──────────────────┐              │
    │  │    ADVISING      │  6 advisors  │
    │  │  (advisors.py)   │  in parallel │
    │  └────────┬─────────┘              │
    │           ▼                         │
    │  ┌──────────────────┐              │
    │  │   SYNTHESIZING   │  Merges all  │
    │  │ (synthesizer.py) │  into plan   │
    │  └────────┬─────────┘              │
    │           ▼                         │
    │  ┌──────────────────┐              │
    │  │   REVIEW GATE    │              │
    │  │                  │              │
    │  │ [a] Approve      │──────────────┼──> Phase 5
    │  │ [r] Re-advise  ──┼──> loop back │
    │  │ [f] Re-frame   ──┼──> Phase 1   │
    │  │ [x] Reject       │──────────────┼──> Phase 5 (rejected)
    │  └──────────────────┘              │
    └─────────────────────────────────────┘
                  │
                  ▼
         ┌──────────────────┐
Phase 5  │  SAVE & OUTPUT   │  Persist plan to disk, print to terminal
         │  (storage.py)    │  User copies into AI coding agent
         └──────────────────┘
```

The review gate lets the user inspect the synthesized plan and choose:
- **Approve** (`a`) -- accept the plan and proceed to save
- **Re-advise** (`r`) -- provide feedback and re-run advisors + synthesis
  (bounded by `max_rounds`, default 3)
- **Re-frame** (`f`) -- go back to framing with corrections, then re-run
  the full advise + synthesize loop
- **Reject** (`x`) -- discard the plan (still saved for reference)

The web UI provides the same review actions via buttons on the plan view,
powered by the `POST /council/review` SSE endpoint.

### Re-advise from history

When a user loads a previously saved plan from history into the session and
clicks "Re-advise":

1. The frontend calls `POST /council/review/init` with the original plan's ID,
   description, and the user's feedback.
2. The backend generates a **new plan_id** (12-char hex), creates a
   **new transcript** with `status="review"` and `base_plan_id` pointing to
   the original plan, copies the original transcript's framer Q&A context,
   and appends the feedback. Returns the new plan_id, the original
   `framed_question`, and the full `framed_requirement` structure.
3. The frontend builds a context-rich prompt containing the full previous
   framed requirement (type, title, stories, acceptance criteria, etc.)
   plus the user's revision feedback, and opens the **framing flow**
   (WebSocket `/ws/framer`). No advisors run at this point.
4. The framer reviews the context, may ask clarifying questions, and
   produces an updated `FramedRequirement`. The normal pipeline then
   continues: confirm -> scan -> advise -> synthesize -> save plan.
5. The plan saved at the end carries `base_plan_id` linking back to the
   original. No plan file is created until synthesis completes.

This creates a linked chain: each review plan points back to its base via
`base_plan_id`, enabling future comparison between plan versions.

### Home screen transcript loading

The home input screen offers a "Load from transcript" option that lists
recent transcripts. Clicking one loads the transcript's framer Q&A context
into a new framing session, allowing the user to continue or revise
previous work without starting from scratch.

---

## Module Descriptions

### `cli.py` (~1400 lines)
Typer CLI entry point. Installed as both `bankai` and `code-council` commands.
Orchestrates the full pipeline including the post-synthesis review loop. Contains:
- `bankai` callback (main command) -- runs `_run_pipeline()`. Flags:
  - `--load <plan_id>` -- resume from a previous plan or transcript
  - `--export <plan_id>` -- export a plan as humanised Markdown
  - `--project / -p` -- path to project to build into
  - `--json` -- output raw JSON
- **Load context resume** (`--load`) -- checks for both saved plans and
  transcripts, then resumes at the appropriate pipeline stage:
  - Plan with `advisor_responses` -> asks whether to re-synthesize (skip all
    the way to Phase 4) or re-run from the confirmation gate
  - Plan with `framed_requirement` only -> skips to the confirmation gate
  - Transcript only (no plan) -> reconstructs framing from the saved Q&A
    pairs and resumes at the confirmation gate
  - Neither found -> shows error
- **Markdown export** (`--export`) -- converts a plan to structured Markdown,
  passes it through the humaniser skill (via LLM) to remove AI writing
  patterns, prints to terminal, and optionally saves to a user-specified file
- Plan ID generation is handled by `generate_plan_id()` in `utils.py` (imported
  as `_generate_plan_id`), which returns a 12-char hex-only ID. Filenames use
  `plan_filename_stem()` to add a human-readable slug. When resuming via
  `--load`, the original plan ID is reused instead of generating a new one,
  so corrections append to the same transcript file.
- `_resolve_load_context()` -- multi-source resolver that checks plans first,
  then transcripts, and returns a resume descriptor with the appropriate
  resume point and available data
- `_extract_qa_pairs()` -- reconstructs `Q: .../A: ...` pairs from transcript
  framer_messages by matching `msg_id` between framer questions and user answers
- `_plan_to_markdown()` -- converts a saved plan dict to structured Markdown
- `_humanise_markdown()` -- passes markdown through the LLM with the humaniser
  skill to clean up AI writing patterns in prose sections
- `_load_humaniser_skill()` -- loads the humaniser skill prompt body from
  `skills/humaniser.md`
- Batch clarification loop (asks all questions from a batch locally, then
  makes one LLM call with all answers to re-evaluate). After every 3 batches,
  pauses to show the framer's current assumptions and remaining questions,
  then asks the user whether to continue or proceed -- never a hard stop.
- Confirmation gate after framing -- displays the full framed requirement
  (type, title, description, acceptance criteria, assumptions, out of scope,
  stories) and asks the user to approve or provide corrections before
  advisors run. Corrections trigger a re-framing LLM call.
- **Review gate** after synthesis -- displays the plan and offers single-key
  actions: `[a]` approve, `[r]` re-advise (with feedback), `[f]` re-frame
  (back to requirements), `[x]` reject. Re-advise loops up to `max_rounds`
  (default 3) negotiation rounds, passing user feedback to advisors via the
  existing `negotiation_feedback` parameter. Re-frame goes all the way back
  to the framing phase with the user's corrections.
- Transcript recording -- initialises a transcript at pipeline start, appends
  each framer question and user answer as the clarification loop runs, and
  records the final framed requirement when clarifications resolve
- `plans` subcommand -- lists recent plans
- `show` subcommand -- displays a specific plan by ID
- `export` subcommand -- same as `--export` flag
- `_format_framed_requirement()` -- formats FramedRequirement for user review
- `_format_plan()` -- formats ChangePlan as terminal-friendly text

### `config.py` (165 lines)
Configuration via `pydantic-settings.BaseSettings`. Reads from environment
variables and optionally from `~/.code-council/env` (KEY=VALUE format).
Environment variables are loaded at module import time so they are available
when `Settings()` is constructed. Factory function `get_settings()` creates
fresh instances for test isolation. Includes `plan_path` and `transcript_path`
properties for deriving storage directories from string settings.

### `llm.py` (286 lines)
LLM client wrapper using the OpenAI Python SDK pointed at a Langdock endpoint.
- `LLMClient` Protocol for structural typing
- `LangdockLLM` implementation with retry (exponential backoff, max 3 retries)
  and `asyncio.wait_for()` timeout
- Both basic API (`complete`/`chat`) and extended API (`complete_with_usage`/
  `chat_with_usage` returning `LLMResult` with token counts)

### `context.py` (617 lines)
Project filesystem scanner that builds structured context for advisors.
- Recursive directory tree builder with depth limiting
- Config file discovery (13 known filenames)
- Tech stack detection (Python, JS/TS, Rust, Go, Java) from config content
- Test pattern detection (framework + directory conventions)
- Keyword-based relevant file scoring
- Three-layer file safety: dotfiles blocked, credential patterns flagged,
  only user-approved files are read

### `framer.py` (268 lines)
Requirements framing -- Phase 1. Takes a raw feature request, calls the LLM
with the framer skill prompt, and produces a `FramedRequirement` (type, title,
description, acceptance criteria, clarifications). Includes
`_backfill_story_types()` to default missing `type` fields in sub-stories
(LLMs sometimes omit them). If `needs_clarification()` is true, the CLI
collects answers for the entire batch of questions locally (no LLM call
between questions), then makes one LLM call with all answers to re-evaluate.
Hard cap of `MAX_CLARIFICATION_BATCHES` (3) prevents infinite loops.

### `advisors.py` (455 lines)
Advisor skill registry and parallel execution engine.
- Auto-discovers advisor skills from `skills/*.md` files
- Parses YAML frontmatter for config (temperature_rank, seed_offset, model override)
- Assigns evenly spaced temperatures across advisors (default range: 0.6--1.0)
- Generates deterministic seeds from SHA-256(plan_id) + offset
- Runs all advisors in parallel via `asyncio.gather()`

### `synthesizer.py` (219 lines)
Plan synthesis -- Phase 4. Takes all advisor responses and produces a single
`ChangePlan` with: plan_id, title, summary, affected files, ordered
implementation steps, notes from each perspective, acceptance criteria,
effort estimate (S/M/L/XL), and risk level (LOW/MEDIUM/HIGH).

### `state.py` (156 lines)
Plan state machine with 9 states:
`FRAMING -> DRAFTING -> PROPOSED -> REVIEWING -> AGREED -> EXECUTING -> COMPLETED`
(plus `REJECTED` and `STALLED` recovery paths). `VALID_TRANSITIONS` dict
enforces legal state changes. Tracks negotiation rounds.

### `storage.py` (~200 lines)
JSON file-based plan persistence at `~/.code-council/plans/`. Filenames use
`plan-<hex>-<slug>.json` for human readability; the stored `plan_id` is the
hex-only identifier. Load and delete use glob matching (`plan-<hex>-*.json`)
with backward-compat exact match for old-format files. Saves plan data, state,
advisor responses, context summary, and timestamps. Forgiving on load (returns
None for missing/corrupt files). Supports `base_plan_id` for linking re-advise
plans back to their original plan.

### `transcript.py` (~230 lines)
Session transcript storage at `~/.code-council/transcripts/`. Records the
running dialogue of a bankai session: original question, every framer exchange
(question, answer, choices), and the final framed requirement. Filenames use
`transcript-<hex>-<slug>.json`; lookup uses glob matching with backward-compat
exact match. Created by both the CLI and the web UI WebSocket framer.
Contains:
- `init_transcript()` -- creates transcript file with original question.
  Accepts optional `base_plan_id` (links review transcripts to their original)
  and `status` (`"active"` for normal, `"review"` for re-advise sessions).
- `append_framer_message()` -- appends a user or framer message
- `set_framed_question()` -- records the final framed requirement text
- `load_transcript()` -- loads transcript by plan_id (None if missing/corrupt)
- `list_recent_transcripts()` -- lists recent transcripts with summary
  metadata (plan_id, timestamp, question, status, message count)

### `utils.py` (~70 lines)
Shared utilities used by both `cli.py` and `daemon.py`:
- `STOP_WORDS` -- frozenset of ~60 common English filler words stripped from
  filename slugs
- `slugify(description)` -- creates a short, filesystem-safe slug from a
  description (strips stop words, keeps first 4 meaningful words, lowercased)
- `generate_plan_id(description)` -- returns a 12-character hex string from
  UUID4. The plan_id is an opaque identifier with no slug component.
- `plan_filename_stem(plan_id, description)` -- builds `<hex>-<slug>` for
  human-readable filenames (e.g., `58cf313f796a-cash-deposit`). Used by
  storage and transcript modules for on-disk filenames while the internal
  `plan_id` remains the short hex string.

### Skill Files (`code_council/skills/`)

Each skill is a Markdown file with YAML frontmatter declaring the advisor's
role, temperature rank, seed offset, enabled flag, and optional model override.
The body contains the system prompt for that advisor.

| File | Type | Temp Rank | Focus Area |
|---|---|---|---|
| `executor.md` | advisor | 0 | TDD, file change sequence, effort, lean incremental delivery, acceptance criteria in integration tests with mocks, test pyramid, code coverage verification |
| `security.md` | advisor | 1 | Input validation, auth, OWASP, secrets |
| `quality.md` | advisor | 2 | Self-documenting code, tests as living documentation, testability, error handling |
| `business.md` | advisor | 3 | Problem validation, value, opportunity cost |
| `architect.md` | advisor | 4 | Module boundaries, coupling, existing patterns |
| `risk.md` | advisor | 5 | Breaking changes, backward compat, rollback |
| `framer.md` | framer | -- | Work classification, acceptance criteria |
| `synthesizer.md` | synthesizer | -- | Conflict resolution, merged actionable plan, enforces self-documenting code, test pyramid, coverage |

Adding a new advisor = dropping a new `.md` file in `skills/` with the correct
frontmatter. No code changes needed.

---

## Data Models

### `FramedRequirement` (framer.py)
```
type: str                          # epic | story | task | bug
title: str                         # Short descriptive title
description: str                   # What and why
acceptance_criteria: list[str]     # Given/When/Then conditions
out_of_scope: list[str]            # Explicitly excluded
assumptions: list[str]             # Assumed to be true
clarifications_needed: list[str]   # Questions blocking progress
stories: list[FramedRequirement]   # Sub-stories for epics
```

### `ProjectContext` (context.py)
```
project_path: str
directory_tree: str
tech_stack: TechStack              # languages, frameworks, package_manager
config_files: dict[str, str]       # filename -> content
relevant_files: dict[str, str]     # relative_path -> content
test_patterns: TestPatterns        # test_framework, test_directory
summary: str
```

### `ChangePlan` (synthesizer.py)
```
plan_id: str
title: str
summary: str
affected_files: list[str]
implementation_steps: list[ImplementationStep]  # order, file_path, action, description, depends_on
architecture_notes: str
security_notes: str
quality_notes: str
risk_assessment: str
execution_strategy: str
acceptance_criteria: list[str]
estimated_effort: str              # S | M | L | XL
risk_level: str                    # LOW | MEDIUM | HIGH
negotiation_round: int
raw_advisor_responses: dict
```

### On-disk plan JSON (storage.py)
```
plan_id: str
timestamp: str                     # ISO-8601 UTC
change_description: str
plan: dict                         # ChangePlan.model_dump()
state: dict                        # PlanState.model_dump() or {"status": "..."}
advisor_responses: dict[str, str]
context_summary: str
framed_requirement: dict | null    # FramedRequirement.model_dump()
base_plan_id: str | null           # original plan this review is based on (null for first plans)
```

### On-disk transcript JSON (transcript.py)
```
plan_id: str
timestamp: str                     # ISO-8601 UTC
question: str                      # original user description
framer_messages: list[dict]        # [{role, text, msg_id?, choices?}, ...]
framed_question: str | null        # final framed requirement text
base_plan_id: str | null           # original plan this review is based on (null for first plans)
status: str                        # "active" for normal, "review" for re-advise sessions
```

### `PlanState` (state.py)
```
plan_id: str
status: PlanStatus                 # FRAMING (initial)
negotiation_round: int
max_rounds: int
negotiation_history: list[NegotiationRound]
error_message: str
```

---

## Dependencies

### Runtime
| Package | Version | Purpose |
|---|---|---|
| `openai` | >= 1.30.0 | AsyncOpenAI client for Langdock endpoint |
| `typer` | >= 0.12.0 | CLI framework |
| `pydantic` | >= 2.7.0 | Data models and validation |
| `pydantic-settings` | >= 2.3.0 | Settings from environment variables |
| `pyyaml` | >= 6.0 | YAML frontmatter parsing for skill files |
| `httpx` | >= 0.27.0 | HTTP client (declared, not directly used yet) |
| `mcp[cli]` | >= 1.2.0 | MCP SDK (declared for future MCP server) |

### Development
| Package | Version | Purpose |
|---|---|---|
| `pytest` | >= 8.0.0 | Test runner |
| `pytest-asyncio` | >= 0.23.0 | Async test support |
| `ruff` | >= 0.4.0 | Linting (rules: E, F, I, W) |

---

## Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `LANGDOCK_API_KEY` | Yes | `""` | API key for Langdock endpoint |
| `LANGDOCK_BASE_URL` | Yes | `""` | Base URL of OpenAI-compatible API |
| `CODE_COUNCIL_MODEL` | No | `REPLACE_ME_WITH_YOUR_MODEL` | Model identifier |
| `CODE_COUNCIL_AGENT_TIMEOUT_SECONDS` | No | `120` | Per-LLM-call timeout (seconds) |
| `CODE_COUNCIL_ADVISOR_TEMPERATURE_SPREAD` | No | `0.4` | Temperature range across advisors |
| `CODE_COUNCIL_MAX_NEGOTIATION_ROUNDS` | No | `3` | Max negotiation rounds |
| `CODE_COUNCIL_SAVE_PLANS` | No | `True` | Whether to persist plans to disk |
| `CODE_COUNCIL_PLAN_DIR` | No | `~/.code-council/plans` | Plan storage directory |
| `CODE_COUNCIL_TRANSCRIPT_DIR` | No | `~/.code-council/transcripts` | Transcript storage directory |

Variables can be set in the shell or in `~/.code-council/env` (KEY=VALUE format,
one per line, `#` comments supported).

---

## Commands

| Command | Description |
|---|---|
| `bankai "description"` | Run full pipeline: frame + scan + advise + synthesize |
| `bankai --json "description"` | Same, but output raw JSON |
| `bankai -p ./path "description"` | Skip project prompt, use given path |
| `bankai --load <plan_id>` | Resume from a previous plan or transcript |
| `bankai --export <plan_id>` | Export a plan as humanised Markdown |
| `bankai export <plan_id>` | Same as `--export` (subcommand form) |
| `bankai plans` | List recent plans |
| `bankai plans -n 5` | List with limit |
| `bankai show <plan-id>` | View a specific plan as JSON |
| `bankai serve` | Start the web UI server (default http://127.0.0.1:8766) |
| `bankai serve --port 9000` | Start on a custom port |

---

## Design Patterns

1. **Protocol-based LLM abstraction** -- `LLMClient` Protocol in each module
   for structural typing. `FakeLLM` in tests satisfies it without inheritance.

2. **Self-describing skill files** -- Advisors defined by `.md` files with YAML
   frontmatter. Adding an advisor = dropping a file. No code changes needed.

3. **Explicit state machine** -- `VALID_TRANSITIONS` dict makes illegal state
   changes unrepresentable. Raises `ValueError` on bad transitions.

4. **Three-layer file safety** -- (1) dotfiles never read, (2) credential
   patterns flagged as sensitive, (3) only user-approved files are read.

5. **Dependency injection** -- Factory functions (`get_settings()`, `get_llm()`)
   enable test isolation. Tests construct their own Settings/FakeLLM instances.

6. **Async throughout** -- `asyncio.gather()` for parallel advisor execution.
   All LLM calls are async with timeout support.

7. **Retry with backoff** -- LLM calls retry up to 3 times with exponential
   backoff (2^attempt seconds).

8. **Incremental transcript storage** -- Transcript file is created at pipeline
   start and appended to after each event (read-modify-write). Progress is
   preserved even if the pipeline crashes mid-session. The web UI WebSocket
   framer also creates and appends to transcripts.

9. **Simple URL routing** -- The web UI uses only two URL routes (`/` and
   `/history`). Plan detail navigation is handled by component state, not
   deep-linked URLs, keeping the router minimal.

---

## Test Suite

17 test files (+ `conftest.py` with shared fixtures) using `FakeLLM` (no real
API calls, 227 tests total). Run with `pytest`.

| Test File | Coverage |
|---|---|
| `test_config.py` | Settings defaults, env overrides, require_langdock, env file loading |
| `test_llm.py` | TokenUsage, LLMResult defaults, FakeLLM response routing |
| `test_skill_registry.py` | Frontmatter parsing, skill discovery, temperature/seed math |
| `test_skill_model_routing.py` | Per-skill model override field |
| `test_context_scanning.py` | Directory tree, tech detection, config files, test patterns |
| `test_context_gather.py` | gather_context integration, nonexistent paths |
| `test_context_approval.py` | Dotfile/credential detection, path discovery safety |
| `test_framer.py` | FramedRequirement model, JSON extraction, frame_request |
| `test_synthesizer.py` | synthesize_plan, JSON extraction, advisor response preservation |
| `test_storage.py` | Save/load/list/delete plans, disabled mode, corrupt JSON |
| `test_state_status.py` | PlanStatus enum values |
| `test_state_transitions.py` | Happy path, invalid transitions, recovery paths |
| `test_state_negotiation.py` | can_negotiate boundary, round recording |
| `test_transcript.py` | Init, append, load, full conversation flow |
| `test_load_context.py` | Plan ID generation, slugify, plan_filename_stem, context resolution, Q&A extraction, resume points |
| `test_export_markdown.py` | Markdown conversion, humaniser skill loader, all plan sections |
| `test_review_init.py` | Re-advise review init: transcript creation, base_plan_id linking, framer context copy, feedback append, no plan created, storage base_plan_id |

---

## Not Yet Implemented

The following are described in `docs/code-council-plan.md` but have no code yet:

- **`mcp_server.py`** -- MCP server for direct AI tool integration
- **`negotiation.py`** -- Feasibility negotiation loop between council and AI tool
- **`serve` CLI command** -- Start the MCP server
