"""Tests for code_council.config -- settings and env loading.

Python lesson: pydantic-settings
    BaseSettings is like Pydantic's BaseModel but it reads values from
    environment variables automatically. If you define a field called
    `langdock_api_key`, it looks for the env var LANGDOCK_API_KEY.
    This means no manual os.environ parsing -- just define the fields
    and Pydantic does the rest.

Python lesson: mock.patch.dict
    `mock.patch.dict(os.environ, {"KEY": "val"}, clear=True)` temporarily
    replaces os.environ with a dict containing only {"KEY": "val"}.
    When the `with` block exits, the original environ is restored.
    `clear=True` means wipe ALL existing env vars for the test.
    `clear=False` means only add/override the specified keys.
"""

import os
from pathlib import Path
from unittest import mock

import pytest

from code_council.config import Settings, _load_env_file


class TestDefaults:
    """Settings should have sensible defaults when no env vars are set."""

    def test_default_negotiation_rounds(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.code_council_max_negotiation_rounds == 3

    def test_default_save_plans(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.code_council_save_plans is True

    def test_default_temperature_spread(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            s = Settings()
        assert s.code_council_advisor_temperature_spread == 0.4


class TestEnvOverrides:
    """Env vars should override defaults."""

    def test_langdock_credentials(self) -> None:
        env = {
            "LANGDOCK_API_KEY": "test-key",
            "LANGDOCK_BASE_URL": "https://test.example.com/v1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            s = Settings()
        assert s.langdock_api_key == "test-key"
        assert s.langdock_base_url == "https://test.example.com/v1"

    def test_model_override(self) -> None:
        with mock.patch.dict(os.environ, {"CODE_COUNCIL_MODEL": "gpt-5"}, clear=True):
            s = Settings()
        assert s.code_council_model == "gpt-5"

    def test_negotiation_rounds_override(self) -> None:
        with mock.patch.dict(
            os.environ, {"CODE_COUNCIL_MAX_NEGOTIATION_ROUNDS": "5"}, clear=True
        ):
            s = Settings()
        assert s.code_council_max_negotiation_rounds == 5


class TestRequireLangdock:
    """require_langdock() should raise when credentials are missing."""

    def test_raises_when_missing(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            s = Settings()
        with pytest.raises(EnvironmentError, match="LANGDOCK_API_KEY"):
            s.require_langdock()

    def test_passes_when_present(self) -> None:
        env = {
            "LANGDOCK_API_KEY": "key",
            "LANGDOCK_BASE_URL": "https://example.com",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            s = Settings()
        s.require_langdock()  # should not raise


class TestPlanPath:
    def test_plan_path_from_env(self) -> None:
        with mock.patch.dict(
            os.environ, {"CODE_COUNCIL_PLAN_DIR": "/tmp/plans"}, clear=True
        ):
            s = Settings()
        assert s.plan_path == Path("/tmp/plans")


class TestLoadEnvFile:
    """_load_env_file reads a KEY=VALUE file into os.environ."""

    def test_loads_values(self, tmp_path: Path) -> None:
        """tmp_path is a pytest fixture that creates a temporary directory.
        Each test gets its own unique temp dir -- no cleanup needed."""
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

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("# comment\n\nTEST_CC_REAL=yes\n")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_CC_REAL", None)
            _load_env_file(env_file)
            assert os.environ["TEST_CC_REAL"] == "yes"
            del os.environ["TEST_CC_REAL"]
