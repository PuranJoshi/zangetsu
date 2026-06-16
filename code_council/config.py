"""Configuration for code-council.

Loads settings from environment variables and optionally from ~/.code-council/env.

Python lesson: pydantic-settings BaseSettings
    Unlike a regular Pydantic BaseModel, BaseSettings automatically reads
    values from environment variables. The mapping is:
        field name               -> ENV VAR
        llm_api_key              -> LLM_API_KEY
        code_council_model       -> CODE_COUNCIL_MODEL

    Environment variables are UPPERCASE, field names are lowercase.
    Pydantic handles the conversion automatically.

Python lesson: _load_env_file pattern
    We call _load_env_file() at MODULE LOAD TIME (line at the bottom).
    This means the env file is read BEFORE Settings() is constructed.
    Why? Because BaseSettings reads os.environ during __init__. If we
    loaded the env file after Settings(), the values wouldn't be there.
    The leading underscore means "private" -- it's an internal helper,
    not part of the public API.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

_ENV_FILE = Path.home() / ".code-council" / "env"


def _load_env_file(path: Path = _ENV_FILE) -> None:
    """Read a simple KEY=VALUE env file and inject into os.environ.

    Lines starting with # and blank lines are ignored.
    Existing environment variables take precedence (never overwritten).

    Why not use python-dotenv?
        We could, but this is 10 lines of code and avoids a dependency.
        The format is intentionally simple: KEY=VALUE, one per line.
        No variable expansion, no multiline values, no export prefix.
    """
    if not path.is_file():
        return
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


# Load env file at import time so values are available for Settings()
_load_env_file()


class Settings(BaseSettings):
    """Central configuration -- all values come from environment variables.

    Usage:
        settings = get_settings()
        settings.require_llm_credentials()  # raises if credentials missing
        print(settings.code_council_model)
    """

    # -- LLM provider --
    llm_api_key: str = Field(
        default="",
        description="API key for the OpenAI-compatible LLM endpoint.",
    )
    llm_base_url: str = Field(
        default="",
        description="Base URL of the OpenAI-compatible LLM API.",
    )
    code_council_model: str = Field(
        default="REPLACE_ME_WITH_YOUR_MODEL",
        description="Model identifier passed to the LLM provider.",
    )

    # -- Agent behaviour --
    code_council_agent_timeout_seconds: int = Field(default=120)
    code_council_advisor_temperature_spread: float = Field(
        default=0.4,
        description=(
            "Range of temperature variation across advisors. "
            "Advisors are assigned temperatures from "
            "(1.0 - spread) to 1.0 based on their role."
        ),
    )

    # -- Negotiation --
    code_council_max_negotiation_rounds: int = Field(
        default=3,
        description="Maximum rounds of plan negotiation with the AI tool.",
    )

    # -- Plans storage --
    code_council_save_plans: bool = Field(default=True)
    code_council_plan_dir: str = Field(
        default=str(Path.home() / ".code-council" / "plans"),
    )

    # -- Transcript storage --
    code_council_transcript_dir: str = Field(
        default=str(Path.home() / ".code-council" / "transcripts"),
        description="Directory for session transcripts.",
    )

    # model_config tells pydantic-settings how to map env vars to fields.
    # env_prefix="" means no prefix -- LLM_API_KEY maps directly.
    # case_sensitive=False means LLM_API_KEY and llm_api_key both work.
    model_config = {"env_prefix": "", "case_sensitive": False}

    # -- Helpers --

    def require_llm_credentials(self) -> None:
        """Raise a clear error if LLM credentials are missing.

        Called before making LLM calls. Fails fast with a message
        telling the user exactly what to set and where.
        """
        missing: list[str] = []
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.llm_base_url:
            missing.append("LLM_BASE_URL")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your shell or in ~/.code-council/env"
            )

    @property
    def plan_path(self) -> Path:
        """Return the plan storage directory as a Path object.

        Python lesson: @property
            Makes a method accessible like an attribute:
                settings.plan_path  (not settings.plan_path())
            Useful when the value is derived from other fields.
        """
        return Path(self.code_council_plan_dir)

    @property
    def transcript_path(self) -> Path:
        """Return the transcript storage directory as a Path object."""
        return Path(self.code_council_transcript_dir)


def get_settings() -> Settings:
    """Return a fresh Settings instance (reads current env).

    Why a factory function instead of a global instance?
        Tests need to construct Settings with different env vars.
        A global singleton would cache the first read. This function
        creates a new instance each time, reading the current os.environ.
    """
    return Settings()


def get_skill_model(skill_name: str) -> str:
    """Look up a per-skill model override from environment variables.

    Checks for ``CODE_COUNCIL_MODEL_<SKILL_NAME>`` (uppercase) in the
    environment. Returns the value if set (non-empty), or empty string
    if not found.

    This covers ALL pipeline skills, not just advisors:
        CODE_COUNCIL_MODEL_ARCHITECT=gpt-4o       -> architect advisor
        CODE_COUNCIL_MODEL_FRAMER=gpt-4o-mini      -> framer
        CODE_COUNCIL_MODEL_SYNTHESIZER=gpt-4o      -> plan synthesizer
        CODE_COUNCIL_MODEL_DECISION_GATE=gpt-4o    -> decision gate
        CODE_COUNCIL_MODEL_HUMANIZER=gpt-4o-mini   -> markdown humaniser
        (not set)                                   -> uses CODE_COUNCIL_MODEL

    This is called during skill discovery and at each pipeline stage
    to allow users to configure per-skill models via environment
    variables or ``~/.code-council/env`` without editing skill files.
    """
    env_key = f"CODE_COUNCIL_MODEL_{skill_name.upper()}"
    return os.environ.get(env_key, "")
