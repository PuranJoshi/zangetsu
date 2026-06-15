"""Project context scanner -- gathers codebase information for advisors.

Scans the target project's filesystem to build a structured understanding
of the codebase. This context is injected into every advisor prompt so they
can give project-specific advice rather than generic guidance.

Python lesson: pathlib.Path
    We use pathlib throughout instead of os.path. pathlib treats paths as
    objects, not strings:
        Path("src") / "main.py"  ->  Path("src/main.py")
        path.is_file()           ->  True/False
        path.read_text()         ->  file contents as string
        path.suffix              ->  ".py"
    It's more readable and less error-prone than os.path.join().

Python lesson: generator expressions
    Several functions use generator patterns like:
        (p for p in root.iterdir() if p.name not in IGNORED_DIRS)
    This creates values lazily -- no list is built in memory. Good for
    scanning large directories where you don't need all entries at once.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TechStack(BaseModel):
    """Detected technology stack."""

    languages: list[str] = []
    frameworks: list[str] = []
    build_tools: list[str] = []
    package_manager: str = ""
    runtime: str = ""


class TestPatterns(BaseModel):
    """Detected testing conventions."""

    test_framework: str = ""
    test_directories: list[str] = []
    test_file_pattern: str = ""
    example_test_files: list[str] = []


class ProjectContext(BaseModel):
    """Structured representation of a project's codebase for advisor consumption."""

    project_path: str
    directory_tree: str = ""
    tech_stack: TechStack = TechStack()
    config_files: dict[str, str] = {}
    relevant_files: dict[str, str] = {}
    test_patterns: TestPatterns = TestPatterns()
    summary: str = ""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directories to always skip when scanning.
# These are either version control, dependency caches, or build artifacts.
IGNORED_DIRS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".tox",
    "egg-info",
    ".eggs",
    ".DS_Store",
    ".idea",
    ".vscode",
}

# Config files to look for, ordered by priority.
# NOTE: no dotfiles here -- .env, .zshrc etc are NEVER read.
CONFIG_FILES: list[str] = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
]

# Max file size to read (skip large generated files)
MAX_FILE_SIZE_BYTES: int = 50_000  # 50 KB

# Max number of relevant files to include in context
MAX_RELEVANT_FILES: int = 20

# Patterns that suggest a file may contain credentials or secrets.
# These files are NEVER auto-read -- they require explicit user confirmation.
# The check is: does the filename (lowercased) contain any of these substrings?
CREDENTIAL_PATTERNS: list[str] = [
    "secret",
    "credential",
    "password",
    "token",
    ".live.",  # application.live.yaml (Kotlin/Spring)
    ".prod.",  # application.prod.yaml
    ".production.",  # config.production.json
    ".staging.",
    "private_key",
    "service_account",
    "keystore",
    ".pem",
    ".key",
    ".p12",
    ".jks",
]


# Dotfiles that are safe to read -- they contain project config, not secrets.
SAFE_DOTFILES: set[str] = {
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
    ".eslintrc",
    ".eslintrc.json",
    ".prettierrc",
    ".prettierrc.json",
    ".flake8",
}


def is_dotfile(name: str) -> bool:
    """Check if a filename is a forbidden dotfile.

    Most dotfiles (.env, .zshrc, .npmrc, etc.) are NEVER read -- they
    frequently contain secrets, credentials, or personal config.

    Exception: some dotfiles are safe project config (.gitignore,
    .editorconfig, etc.) and are allowed through.
    """
    if not name.startswith("."):
        return False
    # Allow known-safe dotfiles
    if name.lower() in SAFE_DOTFILES:
        return False
    return True


def is_potential_credential_file(name: str) -> bool:
    """Check if a filename suggests it might contain credentials.

    Files matching these patterns are flagged for explicit user
    confirmation before reading. Examples:
        application.live.yaml  (Kotlin/Spring production config)
        secrets.json           (credential stores)
        private_key.pem        (certificates)
    """
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in CREDENTIAL_PATTERNS)


# Words to ignore when extracting keywords from change descriptions.
# These are common English words that don't help identify relevant files.
_STOPWORDS: set[str] = {
    "a",
    "an",
    "the",
    "to",
    "in",
    "for",
    "of",
    "and",
    "or",
    "is",
    "it",
    "on",
    "at",
    "by",
    "with",
    "from",
    "as",
    "be",
    "was",
    "that",
    "this",
    "add",
    "new",
    "make",
    "use",
    "change",
    "update",
    "fix",
    "implement",
    "create",
    "should",
    "would",
    "could",
    "can",
    "will",
    "need",
}


# ---------------------------------------------------------------------------
# Scanner functions
# ---------------------------------------------------------------------------


def build_directory_tree(root: Path, max_depth: int = 4) -> str:
    """Build an indented directory tree string.

    Like the Unix `tree` command but skips IGNORED_DIRS.
    Truncates directories with more than 20 entries to keep the output
    manageable for LLM prompts.

    Python lesson: recursion with depth tracking
        _walk() calls itself for subdirectories, decrementing depth.
        When depth reaches 0, we stop recursing. This prevents infinite
        loops and keeps the output size bounded.
    """
    lines: list[str] = []

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth < 0:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        # Separate dirs and files, filter ignored
        dirs = [e for e in entries if e.is_dir() and e.name not in IGNORED_DIRS]
        files = [e for e in entries if e.is_file()]

        all_items = dirs + files
        if len(all_items) > 20:
            all_items = all_items[:20]
            truncated = True
        else:
            truncated = False

        for item in all_items:
            if item.is_dir():
                lines.append(f"{prefix}{item.name}/")
                _walk(item, prefix + "  ", depth - 1)
            else:
                lines.append(f"{prefix}{item.name}")

        if truncated:
            lines.append(f"{prefix}... (truncated)")

    _walk(root, "", max_depth)
    return "\n".join(lines)


def find_config_files(root: Path) -> dict[str, str]:
    """Find and read config files from CONFIG_FILES list.

    Returns a dict mapping filename to contents.
    Only reads files smaller than MAX_FILE_SIZE_BYTES.
    Skips dotfiles entirely -- they are never read.
    """
    result: dict[str, str] = {}
    for name in CONFIG_FILES:
        if is_dotfile(name):
            continue
        path = root / name
        if path.is_file():
            try:
                if path.stat().st_size <= MAX_FILE_SIZE_BYTES:
                    result[name] = path.read_text()
            except OSError as exc:
                logger.warning("Failed to read config file %s: %s", path, exc)
    return result


def detect_tech_stack(root: Path, config_contents: dict[str, str]) -> TechStack:
    """Detect the technology stack from config files and file extensions.

    Python lesson: heuristic-based detection
        This function uses simple string matching, not full parsers.
        "fastapi" in content.lower() is good enough to detect FastAPI.
        A full TOML parser would be more correct but adds complexity
        for marginal benefit -- we're building context for an LLM, not
        a package manager.
    """
    languages: set[str] = set()
    frameworks: set[str] = set()
    build_tools: list[str] = []
    package_manager = ""
    runtime = ""

    # -- Python detection --
    if "pyproject.toml" in config_contents:
        languages.add("Python")
        content = config_contents["pyproject.toml"].lower()
        if "fastapi" in content:
            frameworks.add("FastAPI")
        if "django" in content:
            frameworks.add("Django")
        if "flask" in content:
            frameworks.add("Flask")
        if "hatchling" in content:
            build_tools.append("hatchling")
        if "setuptools" in content:
            build_tools.append("setuptools")
        if "poetry" in content:
            build_tools.append("poetry")

    if "setup.py" in config_contents or "setup.cfg" in config_contents:
        languages.add("Python")

    if "requirements.txt" in config_contents:
        languages.add("Python")

    # -- JavaScript/TypeScript detection --
    if "package.json" in config_contents:
        content = config_contents["package.json"].lower()
        languages.add("JavaScript")
        if "typescript" in content or "tsconfig.json" in config_contents:
            languages.add("TypeScript")
        if "react" in content:
            frameworks.add("React")
        if "vue" in content:
            frameworks.add("Vue")
        if "next" in content:
            frameworks.add("Next.js")
        if "express" in content:
            frameworks.add("Express")

    if "tsconfig.json" in config_contents:
        languages.add("TypeScript")

    # -- Other languages --
    if "Cargo.toml" in config_contents:
        languages.add("Rust")
    if "go.mod" in config_contents:
        languages.add("Go")
    if "pom.xml" in config_contents or "build.gradle" in config_contents:
        languages.add("Java")

    # -- Package manager from lock files --
    lock_files = {
        "poetry.lock": "poetry",
        "pnpm-lock.yaml": "pnpm",
        "yarn.lock": "yarn",
        "package-lock.json": "npm",
        "uv.lock": "uv",
        "Pipfile.lock": "pipenv",
    }
    for lock_file, pm in lock_files.items():
        if (root / lock_file).is_file():
            package_manager = pm
            break

    if not package_manager:
        if "pyproject.toml" in config_contents:
            package_manager = "pip"
        elif "package.json" in config_contents:
            package_manager = "npm"

    return TechStack(
        languages=sorted(languages),
        frameworks=sorted(frameworks),
        build_tools=build_tools,
        package_manager=package_manager,
        runtime=runtime,
    )


def detect_test_patterns(root: Path, tech: TechStack) -> TestPatterns:
    """Detect testing conventions from directory structure and config.

    Looks for common test directories and file naming patterns, then
    infers the test framework.
    """
    test_dirs: list[str] = []
    test_framework = ""
    test_file_pattern = ""
    example_files: list[str] = []

    # Common test directory names
    candidates = ["tests", "test", "__tests__", "spec"]
    for name in candidates:
        path = root / name
        if path.is_dir():
            test_dirs.append(name)

    # Detect framework and patterns based on language
    if "Python" in tech.languages:
        test_framework = "pytest"
        test_file_pattern = "test_*.py"
    elif "JavaScript" in tech.languages or "TypeScript" in tech.languages:
        # Check for vitest vs jest
        if (root / "vitest.config.ts").is_file() or (root / "vitest.config.js").is_file():
            test_framework = "vitest"
        else:
            test_framework = "jest"
        test_file_pattern = "*.test.{ts,js,tsx,jsx}"

    # Find example test files (up to 5)
    for test_dir in test_dirs:
        dir_path = root / test_dir
        try:
            for f in sorted(dir_path.rglob("*")):
                if f.is_file() and len(example_files) < 5:
                    rel = str(f.relative_to(root))
                    example_files.append(rel)
        except (PermissionError, OSError):
            pass

    return TestPatterns(
        test_framework=test_framework,
        test_directories=test_dirs,
        test_file_pattern=test_file_pattern,
        example_test_files=example_files,
    )


def find_relevant_files(
    root: Path,
    change_description: str,
    max_files: int = MAX_RELEVANT_FILES,
) -> dict[str, str]:
    """Find files relevant to the described change.

    Uses keyword matching (no LLM call) to score files by relevance:
    - Filename contains a keyword: +3 points
    - File path contains a keyword: +2 points
    - First 200 chars of content contain a keyword: +1 point

    Python lesson: keyword extraction
        We split the description on whitespace, lowercase everything,
        and remove stopwords. This is intentionally simple -- no NLP,
        no stemming, no embeddings. For finding relevant files in a
        project, exact substring matching on filenames is surprisingly
        effective. "add authentication" -> keywords ["authentication"]
        -> finds auth.py, authentication.py, test_auth.py.
    """
    # Extract keywords
    words = change_description.lower().split()
    keywords = [w for w in words if w not in _STOPWORDS and len(w) > 2]

    if not keywords:
        return {}

    scored: list[tuple[float, str, str]] = []  # (score, rel_path, content)

    def _scan(path: Path) -> None:
        try:
            entries = list(path.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if entry.name in IGNORED_DIRS:
                continue
            if entry.is_dir():
                if is_dotfile(entry.name):
                    continue
                _scan(entry)
            elif entry.is_file():
                # Never read dotfiles or credential files in auto mode
                if is_dotfile(entry.name):
                    continue
                if is_potential_credential_file(entry.name):
                    continue
                try:
                    if entry.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue
                    rel = str(entry.relative_to(root))
                    name_lower = entry.name.lower()
                    path_lower = rel.lower()

                    score = 0.0
                    name_stem = entry.stem.lower()
                    for kw in keywords:
                        if kw in name_lower or name_stem in kw:
                            score += 3
                        elif kw in path_lower:
                            score += 2

                    # Read a snippet for content matching (only if file looks relevant)
                    if score > 0 or entry.suffix in (".py", ".ts", ".js", ".rs", ".go", ".java"):
                        try:
                            snippet = entry.read_text(errors="replace")[:200].lower()
                            for kw in keywords:
                                if kw in snippet:
                                    score += 1
                        except OSError:
                            pass

                    if score > 0:
                        content = entry.read_text(errors="replace")
                        scored.append((score, rel, content))
                except OSError:
                    pass

    _scan(root)

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    return {rel: content for _, rel, content in scored[:max_files]}


def discover_relevant_paths(
    root: Path,
    change_description: str,
    max_files: int = MAX_RELEVANT_FILES,
) -> list[tuple[str, float, bool]]:
    """Find file paths relevant to the change WITHOUT reading their contents.

    Returns a list of (relative_path, relevance_score, is_sensitive) tuples
    sorted by score descending.

    Rules:
    - Dotfiles (starting with .) are NEVER included. They frequently
      contain secrets (.env, .npmrc, .zshrc).
    - Files matching CREDENTIAL_PATTERNS are flagged as sensitive
      (is_sensitive=True). The CLI asks for explicit confirmation.
    - No file content is read here -- that happens in read_approved_files
      after the user approves.
    """
    words = change_description.lower().split()
    keywords = [w for w in words if w not in _STOPWORDS and len(w) > 2]

    if not keywords:
        return []

    scored: list[tuple[str, float, bool]] = []

    def _scan(path: Path) -> None:
        try:
            entries = list(path.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if entry.name in IGNORED_DIRS:
                continue
            if entry.is_dir():
                # Skip dot-directories too (.idea, .config, etc.)
                if is_dotfile(entry.name):
                    continue
                _scan(entry)
            elif entry.is_file():
                # RULE: never include dotfiles
                if is_dotfile(entry.name):
                    continue

                try:
                    if entry.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue
                    rel = str(entry.relative_to(root))
                    name_lower = entry.name.lower()
                    path_lower = rel.lower()
                    name_stem = entry.stem.lower()

                    score = 0.0
                    for kw in keywords:
                        if kw in name_lower or name_stem in kw:
                            score += 3
                        elif kw in path_lower:
                            score += 2

                    if score > 0:
                        sensitive = is_potential_credential_file(entry.name)
                        scored.append((rel, score, sensitive))
                except OSError:
                    pass

    _scan(root)
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_files]


def read_approved_files(root: Path, approved_paths: list[str]) -> dict[str, str]:
    """Read only the user-approved files and return their contents.

    Args:
        root: Project root directory.
        approved_paths: List of relative paths the user approved for reading.

    Returns:
        Dict mapping relative path to file contents.
    """
    result: dict[str, str] = {}
    for rel_path in approved_paths:
        full_path = root / rel_path
        try:
            if full_path.is_file() and full_path.stat().st_size <= MAX_FILE_SIZE_BYTES:
                result[rel_path] = full_path.read_text(errors="replace")
        except OSError as exc:
            logger.warning("Failed to read %s: %s", full_path, exc)
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def gather_context(
    project_path: str,
    change_description: str,
) -> ProjectContext:
    """Main entry point: gather all project context.

    This is the function called by the planning pipeline (bankai command).

    Python lesson: async for consistency
        This function is async even though the filesystem operations are
        synchronous. Why? Because the callers (mcp_server.py, framer.py)
        are async. Having a sync function in an async pipeline requires
        wrapping it in asyncio.to_thread(). Making it async from the
        start is simpler. If file reads become slow (very large projects),
        we can move them to a thread pool later without changing the API.
    """
    root = Path(project_path)
    if not root.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    # Step 1: Build directory tree
    directory_tree = build_directory_tree(root)

    # Step 2: Find and read config files
    config_files = find_config_files(root)

    # Step 3: Detect tech stack
    tech_stack = detect_tech_stack(root, config_files)

    # Step 4: Detect test patterns
    test_patterns = detect_test_patterns(root, tech_stack)

    # Step 5: Find relevant files
    relevant_files = find_relevant_files(root, change_description)

    return ProjectContext(
        project_path=project_path,
        directory_tree=directory_tree,
        tech_stack=tech_stack,
        config_files=config_files,
        relevant_files=relevant_files,
        test_patterns=test_patterns,
        summary="",  # LLM-generated summary is a v2 feature
    )
