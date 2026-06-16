# Code Council -- Agent Instructions

> **Git workflow -- MANDATORY:**
> - **NEVER push directly to `main`.** All changes must go through a Pull Request.
> - Create a feature branch from `main` before making any changes:
>   ```
>   git checkout -b <branch-name> main
>   ```
> - Use descriptive branch names: `feat/<topic>`, `fix/<topic>`, `refactor/<topic>`.
> - Commit your changes to the feature branch, then open a PR against `main`.
> - The PR should have a clear title and description summarising the changes.
>
> **Keeping docs in sync:** Before making changes, check `docs/ARCHITECTURE.md`
> for the current architecture and design.
> After making changes, update `docs/ARCHITECTURE.md`, `README.md`, and this file
> to reflect the new state.
>
> **Verification (run after every change):**
> ```
> .venv/bin/python -m ruff check .                # lint (rules: E, F, I, W)
> .venv/bin/python -m ruff format --check .        # format check (CI runs this!)
> .venv/bin/python -m pytest tests/ -x --tb=short  # tests (263+ tests, no API calls)
> cd web && npm run lint                            # frontend eslint
> cd web && npm run build                           # frontend type check + production build
> ```
> All five must pass before considering a change complete.
> These match the CI pipeline in `.github/workflows/ci.yml` exactly.

## What is Code Council?

Code Council is a CLI planning tool that produces structured implementation
plans through multi-advisor deliberation -- before any code is written.

Invoke with `bankai` followed by a feature request:

```
bankai "Want to build a cash deposit feature"
```

## How It Works

1. **Framing** -- A Requirements Framer defines the work as an epic/story/task/bug
   in Jira-style format. If the request is vague, it asks clarifying questions
   **one at a time** -- each answer is fed back to the LLM, which can then
   adapt, drop resolved questions, or ask new ones. The entire framing
   conversation is recorded as a transcript (`~/.code-council/transcripts/`).

2. **Project Context** -- Optionally scans an existing project for directory
   structure, tech stack, and relevant files. Files require user approval
   before their content is read.

3. **Advising** -- 6 advisors analyze the framed requirements in parallel:
   - Executor (how to build it, step by step, acceptance criteria in integration tests, test pyramid, coverage)
   - Security (vulnerabilities, auth, data exposure)
   - Quality (self-documenting code, tests as living documentation, testability)
   - Business (value, scope, tough questions)
   - Architect (structure, patterns, coupling)
   - Risk (what could break, rollback, blast radius)

4. **Synthesizing** (two-pass) -- First, a conflict analyst reads all advisor
   outputs and produces a structured analysis of agreements, conflicts
   (with resolutions), and emergent insights. Then the plan synthesizer
   uses that analysis to produce a single structured plan with
   implementation steps, affected files, acceptance criteria, risk level,
   and effort estimate.

5. **Council Review** (optional) -- After synthesis, all advisors review
   the plan and return PROCEED or prioritised recommendations. Business &
   Architect act as the decision gate, accepting, deferring, or dropping
   each recommendation. Not all advice makes sense -- they are opinionated.

6. **Output** -- The plan is printed to the terminal (or as JSON). Copy it
   into your AI coding agent (OpenCode, Cursor, GitHub Copilot).

## Commands

| Command | Purpose |
|---|---|
| `bankai "description"` | Plan a code change |
| `bankai --json "description"` | Output plan as raw JSON |
| `bankai -p ./path "description"` | Scan a specific project |
| `bankai --context ctx.json "description"` | Load AI-generated context JSON |
| `bankai --load <plan-id>` | Resume from a previous plan or transcript |
| `bankai --export <plan-id>` | Export a plan as humanised Markdown |
| `bankai export <plan-id>` | Same as `--export` (subcommand form) |
| `bankai plans` | List recent plans |
| `bankai plans -n 5` | List with limit |
| `bankai show <plan-id>` | View a specific plan |
| `bankai serve` | Start web UI server (http://127.0.0.1:8766) |
| `bankai serve --port 9000` | Start on custom port |

## Web UI

The web UI is an optional React + TypeScript frontend (`web/` directory) that
provides a browser-based wizard for the full pipeline. Start it with:

```
bankai serve          # starts FastAPI on port 8766
cd web && npm run dev # starts Vite on port 5176 (proxies to API)
```

The frontend communicates via:
- **WebSocket** `/ws/framer` -- interactive framing Q&A
- **SSE** `/council/stream` -- advisor + synthesis pipeline progress
- **REST** -- project scanning, plans, transcripts

## Skill Files

Advisors are defined by markdown files in `code_council/skills/`. Each file
has YAML frontmatter declaring the advisor's role, temperature, and optional
model override. Adding a new advisor = dropping a new `.md` file.

All skills support per-skill model routing via `CODE_COUNCIL_MODEL_<SKILL_NAME>`.

| Skill | Type | Env Var Override |
|---|---|---|
| `executor.md` | advisor | `CODE_COUNCIL_MODEL_EXECUTOR` |
| `security.md` | advisor | `CODE_COUNCIL_MODEL_SECURITY` |
| `quality.md` | advisor | `CODE_COUNCIL_MODEL_QUALITY` |
| `business.md` | advisor | `CODE_COUNCIL_MODEL_BUSINESS` |
| `architect.md` | advisor | `CODE_COUNCIL_MODEL_ARCHITECT` |
| `risk.md` | advisor | `CODE_COUNCIL_MODEL_RISK` |
| `framer.md` | framer | `CODE_COUNCIL_MODEL_FRAMER` |
| `synthesizer_analysis.md` | synthesizer_analysis | `CODE_COUNCIL_MODEL_SYNTHESIZER_ANALYSIS` |
| `synthesizer.md` | synthesizer | `CODE_COUNCIL_MODEL_SYNTHESIZER` |
| `decision_gate.md` | decision_gate | `CODE_COUNCIL_MODEL_DECISION_GATE` |
| `humaniser.md` | humaniser | `CODE_COUNCIL_MODEL_HUMANIZER` |

## Configuration

Copy `env.example` to `~/.code-council/env` and fill in your values:

```
cp env.example ~/.code-council/env
```

Or set environment variables directly:

```
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
CODE_COUNCIL_MODEL=your-default-model
```

## Storage

| Directory | Contents |
|---|---|
| `~/.code-council/plans/` | Saved plans (JSON, one per pipeline run) |
| `~/.code-council/transcripts/` | Session transcripts (framer Q&A dialogue) |
| `~/.code-council/env` | Environment variables (KEY=VALUE) |

Transcript files are created at pipeline start and appended to incrementally
as each framer question and user answer is exchanged, so progress is preserved
even if the pipeline crashes mid-session.

## Related Documentation

- `docs/ARCHITECTURE.md` -- Full project architecture (modules, data models, dependencies)
- `README.md` -- Setup and usage instructions
