# Code Council -- Architecture

> This document is the single source of truth for understanding the Code Council
> codebase. Keep it in sync with the code whenever modules, commands, or
> architecture change.
>
> **Before making changes:** Check this file for the current architecture.
> **After making changes:** Update this file, `README.md`, and `AGENTS.md` to
> reflect the new state. Run `pytest` to verify nothing is broken.

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
├── README.md                        # Project overview and setup instructions
├── env.example                      # Example ~/.code-council/env with all model options
├── pyproject.toml                   # Build config, dependencies, CLI entry points
├── docs/
│   └── ARCHITECTURE.md              # This file -- full project architecture
├── code_council/                    # Main Python package
│   ├── __init__.py                  # Package init, __version__ = "0.1.0"
│   ├── cli.py                      # Typer CLI entry point (bankai command + subcommands + serve)
│   ├── daemon.py                   # FastAPI server for web UI (WS framer with transcript persistence, SSE pipeline, REST)
│   ├── utils.py                    # Shared utilities (generate_plan_id, slugify, plan_filename_stem)
│   ├── config.py                   # Settings via pydantic-settings + env file loader
│   ├── llm.py                      # OpenAI-compatible LLM wrapper with retry logic
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
│       ├── synthesizer.md          # Plan Synthesizer -- merges all advisor outputs, enforces quality principles
│       └── decision_gate.md       # Decision Gate -- Business+Architect decide on advisor recommendations
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
│       │   ├── useCouncilFeedback.ts # SSE hook for council review (plan feedback + decision gate)
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
│           ├── PlanSidebar.tsx       # Left sidebar: recent plans list
│           ├── TokenUsageSidebar.tsx # Left sidebar: live per-stage token usage display
│           ├── PlanHistory.tsx       # Plan list / history view (detail via component state)
│           ├── CouncilReviewPanel.tsx # Council review: advisor feedback + decision gate display
│           ├── ErrorDisplay.tsx      # Reusable error component (retry/dismiss, compact variant)
│           └── MarkdownContent.tsx   # react-markdown wrapper
└── tests/                          # Test suite (pytest + pytest-asyncio)
    ├── __init__.py
    ├── conftest.py                 # Shared fixtures: FakeLLM, fake_context
    ├── test_config.py              # Settings defaults, env overrides, require_llm_credentials, env file loading
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
Phase 2  │  PROJECT CONTEXT │  Scan local, upload AI-generated JSON, or skip
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
    │  │    ANALYZING     │  Pass 1:     │
    │  │ (synthesizer.py) │  conflicts   │
    │  └────────┬─────────┘              │
    │           ▼                         │
    │  ┌──────────────────┐              │
    │  │   SYNTHESIZING   │  Pass 2:     │
    │  │ (synthesizer.py) │  plan JSON   │
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

### Council Review (feedback loop)

After synthesis, the user can click **Council Review** to get a stakeholder
feedback loop on the final plan:

1. All 6 advisors review the plan from their perspective. Each returns
   either `PROCEED` (plan is sound) or a list of prioritised recommendations.
2. A **Decision Gate** (Business + Architect combined) reviews all
   recommendations and decides for each: `ACCEPT`, `DEFER`, or `DROP`.
   Not all recommendations make sense -- the decision gate is opinionated.
3. The result is displayed as a panel on the plan view: advisor reviews,
   then the final verdict (`PROCEED` or `REVISE`) with decision cards.
4. **User override** -- The user can manually override any decision via
   dropdown selectors on each recommendation card (ACCEPT/DEFER/DROP),
   regardless of what the decision gate suggested.
5. **Apply & Re-plan** -- The user clicks "Apply N changes & re-plan" to
   re-run advisors with the accepted changes as feedback, then re-synthesize.
   The new plan is saved with `council_reviewed` status. The user can also
   **Dismiss** to discard the council review entirely.

This is powered by:
- `POST /council/feedback` (SSE) -- advisor review + decision gate; results
  are persisted to the plan JSON as a `council_review` field via
  `save_council_review()` in `storage.py`
- `POST /council/feedback/apply` (SSE) -- re-synthesize with accepted changes,
  saves plan with `council_reviewed` status

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
Orchestrates the full pipeline including the post-synthesis review loop.
Uses `TokenTracker` to accumulate per-stage token usage and display it
inline after each stage (e.g., `Advisors: 4,200 tokens (3,600 in + 600 out) | Total: 4,350`)
plus a final summary table before saving. Passes `tracker.to_dict()` to
`save_plan()` for persistence. Contains:
- `bankai` callback (main command) -- runs `_run_pipeline()`. Flags:
  - `--load <plan_id>` -- resume from a previous plan or transcript
  - `--export <plan_id>` -- export a plan as humanised Markdown
  - `--project / -p` -- path to project to build into
  - `--context` -- path to a JSON file containing pre-built ProjectContext
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

### `config.py` (~210 lines)
Configuration via `pydantic-settings.BaseSettings`. Reads from environment
variables and optionally from `~/.code-council/env` (KEY=VALUE format).
Environment variables are loaded at module import time so they are available
when `Settings()` is constructed. Factory function `get_settings()` creates
fresh instances for test isolation. Includes `plan_path` and `transcript_path`
properties for deriving storage directories from string settings.
Prompt caching settings (`code_council_prompt_caching`,
`code_council_provider_type`) and `is_anthropic_provider()` helper for
provider detection.

### `llm.py` (~460 lines)
LLM client wrapper using the OpenAI Python SDK pointed at any OpenAI-compatible endpoint.
- `TokenUsage` dataclass with `__add__`, `__iadd__`, `to_dict()` for easy
  accumulation across multiple LLM calls. Includes `cache_creation_tokens`
  and `cache_read_tokens` fields for tracking provider-side prompt caching.
- `LLMResult` dataclass (text + `TokenUsage`)
- `TokenTracker` class -- per-stage token accumulator with `record()`,
  `to_dict()`, `format_stage_line()`, `format_summary()`. Used by
  `cli.py` and `daemon.py` to track and display per-stage + total usage.
  Summary output includes cached token counts when present.
- `LLMClient` Protocol for structural typing (includes `complete`,
  `chat`, `complete_with_usage`, `chat_with_usage`)
- `OpenAICompatibleLLM` implementation with retry (exponential backoff, max 3 retries)
  and `asyncio.wait_for()` timeout
- **Prompt caching**: `complete()` and `complete_with_usage()` accept an optional
  `system_prompt` parameter. When provided and caching is enabled, shared content
  (project context, skill text) is sent as a system message so LLM providers can
  cache and reuse it. For Anthropic, explicit `cache_control` breakpoints are
  added via `_build_system_message()`. For OpenAI, automatic prefix caching
  kicks in for shared prefixes >= 1024 tokens.
- Per-call model override: all methods accept an optional `model` parameter. If
  provided (non-empty), the call uses that model instead of the global default.
  This enables per-skill model routing across the entire pipeline.
- Both basic API (`complete`/`chat` returning `str`) and extended API
  (`complete_with_usage`/`chat_with_usage` returning `LLMResult` with token
  counts). Pipeline modules use the extended API; the basic API remains for
  backward compatibility.

### `context.py` (~800 lines)
Project filesystem scanner that builds structured context for advisors.
- Recursive directory tree builder with depth limiting
- Config file discovery (13 known filenames)
- Tech stack detection (Python, JS/TS, Rust, Go, Java) from config content
- Test pattern detection (framework + directory conventions)
- Keyword-based relevant file scoring
- Three-layer file safety: dotfiles blocked, credential patterns flagged,
  only user-approved files are read
- `generate_context_prompt()` -- builds a tailored AI prompt from the
  change description and framed requirement so users can generate
  `ProjectContext` JSON via an external AI tool instead of scanning locally

### `framer.py` (~280 lines)
Requirements framing -- Phase 1. Takes a raw feature request, calls the LLM
with the framer skill prompt, and produces a `FramedRequirement` (type, title,
description, acceptance criteria, clarifications). Returns
`(FramedRequirement, TokenUsage)` -- the framed result plus accumulated token
usage from all LLM calls in this stage (including retries). Uses
`complete_with_usage()` for token tracking. Supports per-skill model routing
via `CODE_COUNCIL_MODEL_FRAMER`. Includes `_backfill_story_types()` to default
missing `type` fields in sub-stories (LLMs sometimes omit them). If
`needs_clarification()` is true, the CLI collects answers for the entire batch
of questions locally (no LLM call between questions), then makes one LLM call
with all answers to re-evaluate. Hard cap of `MAX_CLARIFICATION_BATCHES` (3)
prevents infinite loops.

### `advisors.py` (~830 lines)
Advisor skill registry, parallel execution engine, and council review.
All functions use `complete_with_usage()` and return `TokenUsage` for tracking.
- Auto-discovers advisor skills from `skills/*.md` files (cached via
  `@functools.lru_cache` after first load)
- Parses YAML frontmatter for config (temperature_rank, seed_offset, model override)
- **Per-advisor model routing**: each advisor can use a different LLM model.
  Model resolution order (highest priority first):
  1. Environment variable `CODE_COUNCIL_MODEL_<SKILL_NAME>`
  2. YAML frontmatter `model:` field in the skill `.md` file
  3. Global `CODE_COUNCIL_MODEL` default (used when model is empty)
- **Prompt caching**: shared project context is extracted into a separate
  `system_prompt` via `_advisor_system_prompt()`. All 6 advisors receive the
  same system message, enabling provider-side cache hits on calls 2-6. Plan
  review and decision gate prompts are similarly split.
- Assigns evenly spaced temperatures across advisors (default range: 0.6--1.0)
- Generates deterministic seeds from SHA-256(plan_id) + offset
- `run_advisors()` -- runs all advisors in parallel via `asyncio.gather()`.
  Returns `(responses, params, timing, token_usage)` 4-tuple.
- `review_plan()` -- each advisor reviews the synthesized plan. Returns
  `(reviews, timing, token_usage)` 3-tuple.
- `decide_changes()` -- Business+Architect decision gate reviews all advisor
  recommendations and decides ACCEPT/DEFER/DROP for each. Returns
  `(decision, token_usage)` tuple. (uses `CODE_COUNCIL_MODEL_DECISION_GATE`
  if set)
- `discover_decision_gate_skill()` -- loads the decision gate skill from skills/

### `synthesizer.py` (~450 lines)
Two-pass plan synthesis -- Phase 4. Both passes use `complete_with_usage()`
and return `TokenUsage` for tracking. Supports per-skill model routing via
`CODE_COUNCIL_MODEL_SYNTHESIZER_ANALYSIS` and `CODE_COUNCIL_MODEL_SYNTHESIZER`.

- **Pass 1 (conflict analysis):** `analyze_conflicts()` reads all advisor
  outputs and produces a structured markdown document identifying
  agreements, conflicts (with resolutions), critical blockers, and emergent
  insights. Returns `(analysis_text, token_usage)`. Uses the
  `synthesizer_analysis.md` skill prompt.
- **Pass 2 (plan generation):** `synthesize_plan()` receives the conflict
  analysis plus the raw advisor outputs and produces a structured
  `ChangePlan` JSON. Returns `(ChangePlan, token_usage)`. The conflict
  analysis gives the synthesizer pre-computed reasoning so it can focus on
  structured output.

Output: `ChangePlan` with plan_id, title, summary, affected files, ordered
implementation steps, notes from each perspective, acceptance criteria,
effort estimate (S/M/L/XL), and risk level (LOW/MEDIUM/HIGH).

### `state.py` (~160 lines)
Plan state machine with 10 states:
`FRAMING -> DRAFTING -> PROPOSED -> REVIEWING -> AGREED -> EXECUTING -> COMPLETED`
(plus `REJECTED`, `STALLED` recovery paths, and `COUNCIL_REVIEWED` for plans
revised after council feedback). `COMPLETED` can transition to `COUNCIL_REVIEWED`
when the user applies accepted council recommendations. `VALID_TRANSITIONS`
dict enforces legal state changes. Tracks negotiation rounds.

### `storage.py` (~290 lines)
JSON file-based plan persistence at `~/.code-council/plans/`. Filenames use
`plan-<hex>-<slug>.json` for human readability; the stored `plan_id` is the
hex-only identifier. Council-reviewed plans are saved as separate
`plan-<hex>-<slug>-revised.json` files so the original plan is preserved for
comparison. Load and delete use glob matching (`plan-<hex>-*.json`) with
backward-compat exact match for old-format files. Saves plan data, state,
advisor responses, context summary, token usage, and timestamps. Forgiving on
load (returns None for missing/corrupt files). Supports `base_plan_id` for
linking re-advise plans back to their original plan. Optional `token_usage`
parameter (from `TokenTracker.to_dict()`) persists per-stage and total token
counts in the plan JSON. `save_council_review()` appends council review results
(advisor reviews + decision gate output) to the original plan file (not the
revised variant) via read-modify-write.

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
| `synthesizer_analysis.md` | synthesizer_analysis | -- | Pass 1: conflict analysis -- identifies agreements, conflicts, resolutions, emergent insights |
| `synthesizer.md` | synthesizer | -- | Pass 2: merged actionable plan from pre-computed analysis, enforces self-documenting code, test pyramid, coverage |
| `decision_gate.md` | decision_gate | -- | Business+Architect decision on advisor plan review recommendations |

Adding a new advisor = dropping a new `.md` file in `skills/` with the correct
frontmatter. No code changes needed.

---

## Data Models

### `TokenUsage` (llm.py)
```
prompt_tokens: int                 # tokens sent to the LLM
completion_tokens: int             # tokens received from the LLM
total_tokens: int                  # prompt + completion
cache_creation_tokens: int         # tokens written to provider cache (Anthropic)
cache_read_tokens: int             # tokens served from cache (Anthropic/OpenAI)
```
Supports `+` / `+=` for accumulation and `to_dict()` for serialization.
Cache fields are populated from the provider's response when prompt caching
is active (Anthropic: `cache_creation_input_tokens` / `cache_read_input_tokens`;
OpenAI: via `getattr` fallback for forward-compatibility).

### `TokenTracker` (llm.py)
```
stage_usage: dict[str, TokenUsage] # per-stage accumulated usage
total: TokenUsage                  # cumulative across all stages
```
Methods: `record(stage, usage)`, `to_dict()`, `format_stage_line(stage)`,
`format_summary()`.

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
code_comments: dict[str, list[str]]  # relative_path -> significant comments
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
token_usage: dict | null           # TokenTracker.to_dict() -- per-stage + total token counts
council_review: dict | null        # Added after council review (see below)
```

### Council review JSON (nested in plan)
```
council_review:
  timestamp: str                   # ISO-8601 UTC when the review completed
  advisor_reviews: dict[str, str]  # advisor_name -> review text ("PROCEED" or recommendations)
  decision:                        # Decision gate output
    verdict: str                   # "PROCEED" or "REVISE"
    rationale: str
    decisions: list                # per-recommendation decisions
      - advisor: str
        recommendation: str
        priority: str              # HIGH | MEDIUM | LOW
        decision: str              # ACCEPT | DEFER | DROP
        reason: str
    accepted_changes_summary: str
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
| `openai` | >= 1.30.0 | AsyncOpenAI client for OpenAI-compatible endpoints |
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
| `LLM_API_KEY` | Yes | `""` | API key for the LLM endpoint |
| `LLM_BASE_URL` | Yes | `""` | Base URL of OpenAI-compatible API |
| `CODE_COUNCIL_MODEL` | No | `REPLACE_ME_WITH_YOUR_MODEL` | Model identifier |
| `CODE_COUNCIL_AGENT_TIMEOUT_SECONDS` | No | `120` | Per-LLM-call timeout (seconds) |
| `CODE_COUNCIL_ADVISOR_TEMPERATURE_SPREAD` | No | `0.4` | Temperature range across advisors |
| `CODE_COUNCIL_MAX_NEGOTIATION_ROUNDS` | No | `3` | Max negotiation rounds |
| `CODE_COUNCIL_SAVE_PLANS` | No | `True` | Whether to persist plans to disk |
| `CODE_COUNCIL_PLAN_DIR` | No | `~/.code-council/plans` | Plan storage directory |
| `CODE_COUNCIL_TRANSCRIPT_DIR` | No | `~/.code-council/transcripts` | Transcript storage directory |
| `CODE_COUNCIL_PROMPT_CACHING` | No | `True` | Enable LLM prompt caching (system message split) |
| `CODE_COUNCIL_PROVIDER_TYPE` | No | `auto` | Provider type for cache strategy: `auto`, `anthropic`, `openai`, `none` |

Variables can be set in the shell or in `~/.code-council/env` (KEY=VALUE format,
one per line, `#` comments supported).

---

## Commands

| Command | Description |
|---|---|
| `bankai "description"` | Run full pipeline: frame + scan + advise + synthesize |
| `bankai --json "description"` | Same, but output raw JSON |
| `bankai -p ./path "description"` | Skip project prompt, use given path |
| `bankai --context ctx.json "description"` | Load AI-generated ProjectContext from JSON file |
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
   Each skill can use a different model via `CODE_COUNCIL_MODEL_<SKILL_NAME>`
   env vars or `model:` in frontmatter. All pipeline stages (framer, advisors,
   synthesizer, decision gate, humanizer) support per-skill model routing.

3. **Explicit state machine** -- `VALID_TRANSITIONS` dict (10 states) makes
   illegal state changes unrepresentable. Raises `ValueError` on bad
   transitions. Includes `COUNCIL_REVIEWED` for plans revised after council
   feedback.

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

10. **Per-stage token tracking** -- Every `complete_with_usage()` /
    `chat_with_usage()` call returns `TokenUsage` alongside the text.
    Pipeline functions return it as part of their result tuples.
    `TokenTracker` accumulates per-stage totals. CLI displays inline +
    summary table. Web UI streams `token_usage/update` SSE events into
    `TokenUsageSidebar`. Framing tokens are tracked via WebSocket messages.
    All token data is persisted in the saved plan JSON.

11. **LLM prompt caching** -- Shared content (project context, skill text)
    is split into system messages so LLM providers can cache it across
    calls. All 6 advisor calls share an identical system message prefix,
    enabling cache hits on calls 2-6. Anthropic: explicit `cache_control`
    breakpoints (90% discount). OpenAI: automatic prefix caching for
    prefixes >= 1024 tokens (50% discount). Controlled by
    `CODE_COUNCIL_PROMPT_CACHING` (default: `True`) and
    `CODE_COUNCIL_PROVIDER_TYPE` (default: `auto`).

12. **In-memory skill file caching** -- Skill discovery functions
    (`discover_advisor_skills`, `discover_synthesizer_skill`, etc.) use
    `@functools.lru_cache` to avoid redundant filesystem reads and YAML
    parsing during a pipeline run. Skill files are read once on first call
    and cached for the process lifetime.

---

## Test Suite

17 test files (+ `conftest.py` with shared fixtures) using `FakeLLM` (no real
API calls, 278 tests total). Run with `pytest`.

| Test File | Coverage |
|---|---|
| `test_config.py` | Settings defaults, env overrides, require_llm_credentials, env file loading, prompt caching config (provider detection, auto/anthropic/openai/none) |
| `test_llm.py` | TokenUsage (defaults, add, iadd, to_dict, cache fields), LLMResult, TokenTracker (record, accumulate, to_dict, format, cache display), FakeLLM response routing + system_prompt support |
| `test_skill_registry.py` | Frontmatter parsing, skill discovery, temperature/seed math |
| `test_skill_model_routing.py` | Per-skill model override field, env var overrides, runtime model routing, non-advisor skills, config/skill mismatch edge cases |
| `test_context_scanning.py` | Directory tree, tech detection, config files, test patterns |
| `test_context_gather.py` | gather_context integration, nonexistent paths |
| `test_context_approval.py` | Dotfile/credential detection, path discovery safety |
| `test_framer.py` | FramedRequirement model, JSON extraction, frame_request |
| `test_synthesizer.py` | synthesize_plan, JSON extraction, advisor response preservation |
| `test_storage.py` | Save/load/list/delete plans, disabled mode, corrupt JSON |
| `test_state_status.py` | PlanStatus enum values |
| `test_state_transitions.py` | Happy path, invalid transitions, council review transitions, recovery paths |
| `test_state_negotiation.py` | can_negotiate boundary, round recording |
| `test_transcript.py` | Init, append, load, full conversation flow |
| `test_load_context.py` | Plan ID generation, slugify, plan_filename_stem, context resolution, Q&A extraction, resume points |
| `test_export_markdown.py` | Markdown conversion, humaniser skill loader, all plan sections |
| `test_review_init.py` | Re-advise review init: transcript creation, base_plan_id linking, framer context copy, feedback append, no plan created, storage base_plan_id |

---

## Not Yet Implemented

The following are planned but have no code yet:

- **`mcp_server.py`** -- MCP server for direct AI tool integration
- **`negotiation.py`** -- Feasibility negotiation loop between council and AI tool
- **`serve` CLI command** -- Start the MCP server
