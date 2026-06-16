# Code Council

A CLI tool that plans code changes through multi-advisor deliberation --
before any code is written.

Describe a feature in plain English. Code Council frames it as structured
requirements, runs 6 independent technical advisors in parallel, and
synthesizes a single actionable implementation plan you can hand to your
AI coding agent.

## Requirements

- Python >= 3.11
- An OpenAI-compatible API endpoint (OpenAI, Azure OpenAI, Ollama, LM Studio, Groq, Together AI, etc.)

## Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd zangetsu

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install in development mode
pip install -e ".[dev]"

# 4. Configure credentials (copy the example and fill in your values)
mkdir -p ~/.code-council
cp env.example ~/.code-council/env
# Edit ~/.code-council/env with your API key and model
```

Alternatively, export the variables directly in your shell:

```bash
export LLM_API_KEY=your-api-key
export LLM_BASE_URL=https://api.openai.com/v1
export CODE_COUNCIL_MODEL=your-model-identifier
```

## Usage

```bash
# Plan a feature
bankai "Add user authentication to the API"

# Plan with a specific project path (skips the interactive project prompt)
bankai -p ./my-app "Add JWT auth"

# Load AI-generated project context from a JSON file
bankai --context project-context.json "Add JWT auth"

# Output raw JSON instead of formatted text
bankai --json "Build a caching layer"

# List recent plans
bankai plans
bankai plans -n 5

# View a specific plan
bankai show <plan-id>
```

## How It Works

1. **Framing** -- The Requirements Framer classifies the work (epic / story /
   task / bug) and produces structured requirements. If the request is vague,
   it asks clarifying questions one at a time until all ambiguity is resolved.
   The entire framing conversation (questions, answers, final requirement) is
   saved as a transcript in `~/.code-council/transcripts/`.

2. **Project Context** -- Optionally provides project context via three methods:
   scan a local directory (with user approval before reading files), upload
   AI-generated context JSON (the tool generates a tailored prompt you give to
   your AI coding tool), or skip for greenfield projects.

3. **Advising** -- 6 advisors analyze the requirements in parallel:
   - **Executor** -- how to build it, step by step, acceptance criteria in integration tests, test pyramid, coverage
   - **Security** -- vulnerabilities, auth, data exposure
   - **Quality** -- self-documenting code, tests as living documentation, testability
   - **Business** -- value, scope, tough questions
   - **Architect** -- structure, patterns, coupling
   - **Risk** -- what could break, rollback, blast radius

4. **Synthesizing** -- A synthesizer merges all advisor outputs into a single
   plan with implementation steps, affected files, acceptance criteria, risk
   level, and effort estimate.

5. **Output** -- The plan is printed to the terminal (or as JSON). Copy it
   into your AI coding agent (OpenCode, Cursor, GitHub Copilot).

## Adding Advisors

Advisors are defined by Markdown files in `code_council/skills/`. Each file
has YAML frontmatter declaring the advisor's role, temperature rank, and seed
offset. Adding a new advisor = dropping a new `.md` file. No code changes
needed.

## Per-Skill Model Routing

Every pipeline stage can use a different LLM model. By default all stages use
`CODE_COUNCIL_MODEL`. Only override when you have a specific reason --
reasoning-heavy models cost significantly more and run slower.

Model resolution order (highest priority first):
1. Environment variable `CODE_COUNCIL_MODEL_<SKILL_NAME>`
2. YAML frontmatter `model:` field in the skill `.md` file
3. Global `CODE_COUNCIL_MODEL` default

### All configurable skill models

| Env Var | Pipeline Stage | Calls per plan |
|---|---|---|
| `CODE_COUNCIL_MODEL` | Global default for all stages | -- |
| `CODE_COUNCIL_MODEL_FRAMER` | Requirements framing | 1 + clarification rounds |
| `CODE_COUNCIL_MODEL_EXECUTOR` | Executor advisor | 1 |
| `CODE_COUNCIL_MODEL_SECURITY` | Security advisor | 1 |
| `CODE_COUNCIL_MODEL_QUALITY` | Quality advisor | 1 |
| `CODE_COUNCIL_MODEL_BUSINESS` | Business advisor | 1 |
| `CODE_COUNCIL_MODEL_ARCHITECT` | Architect advisor | 1 |
| `CODE_COUNCIL_MODEL_RISK` | Risk advisor | 1 |
| `CODE_COUNCIL_MODEL_SYNTHESIZER_ANALYSIS` | Conflict analysis (Pass 1) | 1 |
| `CODE_COUNCIL_MODEL_SYNTHESIZER` | Plan synthesis (Pass 2) | 1 |
| `CODE_COUNCIL_MODEL_DECISION_GATE` | Council review decision gate | 1 |
| `CODE_COUNCIL_MODEL_HUMANIZER` | Markdown export humaniser | 1 |

Example `~/.code-council/env` (all skills set to cheap defaults):

```bash
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1

CODE_COUNCIL_MODEL=gpt-4o-mini
CODE_COUNCIL_MODEL_FRAMER=gpt-4o-mini
CODE_COUNCIL_MODEL_EXECUTOR=gpt-4o-mini
CODE_COUNCIL_MODEL_SECURITY=gpt-4o-mini
CODE_COUNCIL_MODEL_QUALITY=gpt-4o-mini
CODE_COUNCIL_MODEL_BUSINESS=gpt-4o-mini
CODE_COUNCIL_MODEL_ARCHITECT=gpt-4o-mini
CODE_COUNCIL_MODEL_RISK=gpt-4o-mini
CODE_COUNCIL_MODEL_SYNTHESIZER_ANALYSIS=gpt-4o-mini
CODE_COUNCIL_MODEL_SYNTHESIZER=gpt-4o-mini
CODE_COUNCIL_MODEL_DECISION_GATE=gpt-4o-mini
CODE_COUNCIL_MODEL_HUMANIZER=gpt-4o-mini
```

A ready-to-copy version of this is available in `env.example`.

## Environment Variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `LLM_API_KEY` | Yes | -- | API key for the LLM endpoint |
| `LLM_BASE_URL` | Yes | -- | Base URL of the OpenAI-compatible API |
| `CODE_COUNCIL_MODEL` | No | `REPLACE_ME_WITH_YOUR_MODEL` | Model identifier |
| `CODE_COUNCIL_AGENT_TIMEOUT_SECONDS` | No | `120` | Per-call timeout |
| `CODE_COUNCIL_ADVISOR_TEMPERATURE_SPREAD` | No | `0.4` | Temperature range |
| `CODE_COUNCIL_MAX_NEGOTIATION_ROUNDS` | No | `3` | Max negotiation rounds |
| `CODE_COUNCIL_SAVE_PLANS` | No | `True` | Persist plans to disk |
| `CODE_COUNCIL_PLAN_DIR` | No | `~/.code-council/plans` | Plan storage path |
| `CODE_COUNCIL_TRANSCRIPT_DIR` | No | `~/.code-council/transcripts` | Transcript storage path |
| `CODE_COUNCIL_PROMPT_CACHING` | No | `True` | Enable LLM prompt caching |
| `CODE_COUNCIL_PROVIDER_TYPE` | No | `auto` | Cache strategy: `auto`, `anthropic`, `openai`, `none` |

## Running Tests

```bash
# Run all tests (no API calls -- uses FakeLLM)
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_framer.py
```

## Linting

```bash
ruff check code_council/
ruff check --fix code_council/   # auto-fix
```

## Project Documentation

| Document | Purpose |
|---|---|
| `docs/ARCHITECTURE.md` | Full project architecture -- modules, data models, dependencies |
| `AGENTS.md` | AI agent instructions for Code Council |
| `CONTRIBUTING.md` | Contribution guidelines and development workflow |
| `CODE_OF_CONDUCT.md` | Community standards and expectations |

## Keeping Documentation in Sync

When making changes to the codebase, update these files to stay in sync:

1. **Before making changes:** Read `docs/ARCHITECTURE.md` to understand the
   current architecture.
2. **After making changes:** Update `docs/ARCHITECTURE.md`, `README.md`, and
   `AGENTS.md` to reflect the new state (line counts, module descriptions,
   commands, etc.).
3. **Run tests:** Always run `pytest` after changes to verify nothing is broken.
