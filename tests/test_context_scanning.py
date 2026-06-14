"""Tests for context.py -- filesystem scanning and tech detection.

Python lesson: tmp_path for filesystem tests
    Every test here gets a `tmp_path` (a fresh temporary directory).
    We create fake project structures inside it, then run the scanner
    functions against them. This means tests don't depend on any real
    project existing on disk -- they're fully self-contained.

Python lesson: why test filesystem code at all?
    "It just reads files, what could go wrong?" A lot:
    - Does it skip .git and node_modules?
    - Does it handle missing directories gracefully?
    - Does it detect Python vs JavaScript correctly?
    - Does it score relevant files sensibly?
    These are all heuristics with edge cases. Tests pin the behaviour.
"""

from pathlib import Path

import pytest

from code_council.context import (
    build_directory_tree,
    detect_tech_stack,
    find_config_files,
    detect_test_patterns,
    find_relevant_files,
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

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        """Deeply nested dirs should stop at max_depth."""
        deep = tmp_path / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        (deep / "file.py").write_text("x")

        tree = build_directory_tree(tmp_path, max_depth=2)
        assert "a" in tree
        assert "b" in tree
        # "e" is at depth 5, should not appear with max_depth=2
        assert "e" not in tree

    def test_empty_directory(self, tmp_path: Path) -> None:
        tree = build_directory_tree(tmp_path)
        assert tree == "" or tree.strip() == ""


class TestTechStackDetection:
    def test_detects_python_from_pyproject(self, tmp_path: Path) -> None:
        config = {"pyproject.toml": '[project]\nname="myapp"\ndependencies=["fastapi"]'}
        tech = detect_tech_stack(tmp_path, config)
        assert "Python" in tech.languages

    def test_detects_fastapi_framework(self, tmp_path: Path) -> None:
        config = {"pyproject.toml": '[project]\ndependencies=["fastapi>=0.100"]'}
        tech = detect_tech_stack(tmp_path, config)
        assert any("fastapi" in f.lower() for f in tech.frameworks)

    def test_detects_node_project(self, tmp_path: Path) -> None:
        config = {"package.json": '{"dependencies": {"react": "^18"}}'}
        tech = detect_tech_stack(tmp_path, config)
        assert any(l in tech.languages for l in ["JavaScript", "TypeScript"])

    def test_detects_react_framework(self, tmp_path: Path) -> None:
        config = {"package.json": '{"dependencies": {"react": "^18"}}'}
        tech = detect_tech_stack(tmp_path, config)
        assert any("react" in f.lower() for f in tech.frameworks)

    def test_unknown_project(self, tmp_path: Path) -> None:
        """No config files -> should still return a valid TechStack."""
        tech = detect_tech_stack(tmp_path, {})
        assert isinstance(tech.languages, list)


class TestFindConfigFiles:
    def test_finds_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname="test"')
        configs = find_config_files(tmp_path)
        assert "pyproject.toml" in configs

    def test_finds_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "test"}')
        configs = find_config_files(tmp_path)
        assert "package.json" in configs

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        """Only finds files that actually exist."""
        configs = find_config_files(tmp_path)
        assert len(configs) == 0


class TestDetectTestPatterns:
    def test_detects_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("def test_x(): pass")
        from code_council.context import TechStack
        tech = TechStack(languages=["Python"])
        patterns = detect_test_patterns(tmp_path, tech)
        assert patterns.test_framework == "pytest"
        assert "tests" in str(patterns.test_directories)

    def test_detects_jest(self, tmp_path: Path) -> None:
        (tmp_path / "__tests__").mkdir()
        (tmp_path / "__tests__" / "app.test.js").write_text("test('x', () => {})")
        from code_council.context import TechStack
        tech = TechStack(languages=["JavaScript"])
        patterns = detect_test_patterns(tmp_path, tech)
        assert patterns.test_framework in ("jest", "vitest")


class TestFindRelevantFiles:
    def test_scores_by_keyword_match(self, tmp_path: Path) -> None:
        (tmp_path / "auth.py").write_text("def login(): pass")
        (tmp_path / "utils.py").write_text("def helper(): pass")
        (tmp_path / "auth_test.py").write_text("def test_login(): pass")

        relevant = find_relevant_files(tmp_path, "add authentication login")
        # auth files should appear (keyword match)
        keys = list(relevant.keys())
        assert any("auth" in k for k in keys)

    def test_limits_results(self, tmp_path: Path) -> None:
        for i in range(30):
            (tmp_path / f"file_{i}.py").write_text(f"# file {i}")

        relevant = find_relevant_files(tmp_path, "test", max_files=5)
        assert len(relevant) <= 5

    def test_skips_ignored_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "auth.js").write_text("module")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "auth.py").write_text("def login(): pass")

        relevant = find_relevant_files(tmp_path, "auth")
        keys_str = " ".join(relevant.keys())
        assert "node_modules" not in keys_str
