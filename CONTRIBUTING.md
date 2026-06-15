# Contributing to Code Council

Thank you for considering a contribution to Code Council. This guide covers
everything you need to get started.

## Getting Started

### Prerequisites

- Python >= 3.11
- Node.js >= 22 (for the web UI)
- Git

### Development Setup

```bash
# Clone the repository
git clone <repo-url>
cd zangetsu

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# (Optional) Set up the web UI
cd web
npm ci
cd ..
```

### Configuration

Create a credentials file or export environment variables:

```bash
mkdir -p ~/.code-council
cat > ~/.code-council/env << 'EOF'
LANGDOCK_API_KEY=your-api-key
LANGDOCK_BASE_URL=https://your-langdock-url/v1
CODE_COUNCIL_MODEL=your-model-identifier
EOF
```

See `README.md` for the full list of environment variables.

## Development Workflow

1. **Fork and clone** the repository.
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Before making changes** -- read `docs/ARCHITECTURE.md` to understand the
   current architecture.
4. **Make your changes** -- keep commits focused and atomic.
5. **After making changes** -- update `docs/ARCHITECTURE.md`, `README.md`, and `AGENTS.md`
   to reflect the new state (line counts, module descriptions, commands, etc.).
6. **Run `pytest`** to verify nothing is broken.
7. **Run linting** before pushing (see below).
8. **Open a pull request** against `main`.

## Running Tests

All tests use `FakeLLM` -- no real API calls are made.

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_framer.py

# Run a specific test by name
pytest -k "test_happy_path"
```

## Linting

The project uses [Ruff](https://docs.astral.sh/ruff/) for Python linting
and formatting.

```bash
# Check for lint errors
ruff check .

# Check formatting
ruff format --check .

# Auto-fix lint issues
ruff check --fix .

# Auto-format
ruff format .
```

For the web UI:

```bash
cd web
npm run lint
npm run build   # also runs TypeScript type checking
```

## Code Style

### Python

- Follow existing patterns in the codebase.
- Ruff is configured with rules `E`, `F`, `I`, `W` and a line length of 100.
- Use type hints for function signatures.
- Use `async`/`await` for I/O-bound operations.
- Follow the protocol-based dependency injection pattern (see `llm.py` for
  the `LLMClient` Protocol).

### TypeScript (Web UI)

- ESLint is configured with TypeScript and React plugins.
- Use functional components with hooks.
- Keep types in `types.ts` when shared across components.

## Project Structure

```
code_council/          Python package (CLI, pipeline, advisors)
code_council/skills/   Advisor skill files (Markdown + YAML frontmatter)
web/                   React + TypeScript frontend (Vite + Tailwind)
tests/                 Python test suite (pytest)
```

See `docs/ARCHITECTURE.md` for a detailed architecture overview.

## Adding an Advisor

Adding a new advisor requires no code changes. Drop a new `.md` file in
`code_council/skills/` with the correct YAML frontmatter:

```yaml
---
name: Your Advisor Name
type: advisor
temperature_rank: 6   # next available rank
seed_offset: 600
enabled: true
---

Your system prompt here...
```

The skill registry auto-discovers files in `skills/`.

## Writing Tests

- Place test files in `tests/` with the `test_` prefix.
- Use the shared `FakeLLM` and `fake_context` fixtures from `conftest.py`.
- Group related tests in classes (`class TestFeatureName`).
- Use type annotations on test methods.
- Async tests are automatically detected (`asyncio_mode = "auto"`).

## Keeping Documentation in Sync

This is a strict requirement. Three documents must stay in sync with the code:

| Document | What to update |
|---|---|
| `docs/ARCHITECTURE.md` | Architecture, modules, data models, line counts, dependencies |
| `README.md` | Setup instructions, usage, commands, environment variables |
| `AGENTS.md` | AI agent instructions, skill table, command table |

## Pull Request Guidelines

- Keep PRs focused on a single concern.
- Include tests for new functionality.
- Run `pytest` and `ruff check .` before submitting.
- Update `docs/ARCHITECTURE.md`, `README.md`, and `AGENTS.md` if your change affects
  architecture, modules, commands, or configuration.
- Write a clear PR description explaining **what** changed and **why**.
- PRs require approval from code owners before merging.
- CI must pass (Python tests + linting, frontend lint + build).

## Reporting Issues

Open an issue on GitHub with:

- A clear description of the problem or feature request.
- Steps to reproduce (for bugs).
- Expected vs. actual behaviour.
- Python version and OS.

## License

By contributing, you agree that your contributions will be licensed under the
MIT License.
