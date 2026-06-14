"""Tests for gather_context -- the main entry point that assembles everything.

Python lesson: @pytest.mark.asyncio
    gather_context is an async function. Regular test functions can't
    call `await`. The @pytest.mark.asyncio decorator tells pytest to
    run this test inside an event loop so `await` works.

    We have `asyncio_mode = "auto"` in pyproject.toml, which should
    auto-detect async tests. But explicit marking is clearer and works
    across all pytest-asyncio versions.
"""

from pathlib import Path

import pytest

from code_council.context import gather_context


@pytest.mark.asyncio
async def test_gather_returns_complete_context(tmp_path: Path) -> None:
    """Set up a minimal project and verify all context fields populate."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")

    ctx = await gather_context(str(tmp_path), "add a feature")
    assert ctx.project_path == str(tmp_path)
    assert ctx.directory_tree != ""
    assert "pyproject.toml" in ctx.config_files
    assert len(ctx.tech_stack.languages) > 0


@pytest.mark.asyncio
async def test_gather_with_nonexistent_path() -> None:
    """Should raise for a path that doesn't exist."""
    with pytest.raises(FileNotFoundError):
        await gather_context("/tmp/nonexistent_project_xyz_123", "test")


@pytest.mark.asyncio
async def test_gather_populates_relevant_files(tmp_path: Path) -> None:
    """Relevant files should match keywords from the change description."""
    (tmp_path / "auth.py").write_text("def login(): pass")
    (tmp_path / "utils.py").write_text("def helper(): pass")

    ctx = await gather_context(str(tmp_path), "add authentication")
    # auth.py should be in relevant files (keyword match)
    assert len(ctx.relevant_files) > 0
