# Code Council -- Agent Instructions

> **Keeping docs in sync:** Before making changes, check `docs/ARCHITECTURE.md`
> for the current architecture and design.
> After making changes, update `docs/ARCHITECTURE.md`, `README.md`, and this file
> to reflect the new state. Run `pytest` to verify nothing is broken.

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

4. **Synthesizing** -- A synthesizer merges all advisor outputs into a single
   structured plan with implementation steps, affected files, acceptance
   criteria, risk level, and effort estimate.

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

| Skill | Type | Model Override |
|---|---|---|
| `executor.md` | advisor | (default) |
| `security.md` | advisor | (default) |
| `quality.md` | advisor | (default) |
| `business.md` | advisor | (configurable) |
| `architect.md` | advisor | (configurable) |
| `risk.md` | advisor | (default) |
| `synthesizer.md` | synthesizer | (default) |
| `decision_gate.md` | decision_gate | (default) |
| `framer.md` | framer | (default) |

## Configuration

Set these environment variables (or put them in `~/.code-council/env`):

```
LANGDOCK_API_KEY=your-api-key
LANGDOCK_BASE_URL=https://your-langdock-url/v1
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
