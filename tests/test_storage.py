"""Tests for code_council.storage -- JSON plan persistence.

Python lesson: tmp_path fixture
    pytest provides `tmp_path` as a built-in fixture. Each test gets a
    unique temporary directory (a pathlib.Path). It's auto-cleaned after
    the test session. Use it whenever tests need to read/write files --
    never write to real paths in tests.

Python lesson: why inject settings?
    Instead of calling get_settings() inside storage functions, we pass
    `settings` as a parameter. This is dependency injection -- it lets
    tests provide a Settings object pointing to tmp_path instead of the
    real ~/.code-council/plans directory. No monkey-patching needed.
"""

import json
import os
from pathlib import Path
from unittest import mock

from code_council.config import Settings
from code_council.storage import delete_plan, list_recent_plans, load_plan, save_plan


def _test_settings(tmp_path: Path) -> Settings:
    """Create a Settings instance pointing to a temp directory."""
    with mock.patch.dict(os.environ, {}, clear=True):
        s = Settings()
    s.code_council_save_plans = True
    s.code_council_plan_dir = str(tmp_path)
    return s


class TestSavePlan:
    def test_saves_to_disk(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        path = save_plan(
            plan_id="test-1",
            change_description="Add auth",
            plan_data={"title": "Add Auth"},
            state_data={"status": "proposed"},
            advisor_responses={"Architect": "Looks good."},
            context_summary="Python FastAPI project.",
            settings=settings,
        )
        assert path is not None
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data["plan_id"] == "test-1"
        assert data["change_description"] == "Add auth"

    def test_disabled_returns_none(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        settings.code_council_save_plans = False
        result = save_plan(
            plan_id="x",
            change_description="y",
            plan_data={},
            state_data={},
            advisor_responses={},
            context_summary="",
            settings=settings,
        )
        assert result is None

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        """The plans directory should be created automatically."""
        nested = tmp_path / "deep" / "plans"
        settings = _test_settings(tmp_path)
        settings.code_council_plan_dir = str(nested)
        path = save_plan(
            plan_id="auto-dir",
            change_description="test",
            plan_data={},
            state_data={},
            advisor_responses={},
            context_summary="",
            settings=settings,
        )
        assert path is not None
        assert nested.is_dir()


class TestLoadPlan:
    def test_loads_existing(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan-abc.json"
        plan_file.write_text(json.dumps({"plan_id": "abc", "title": "Test"}))
        settings = _test_settings(tmp_path)
        data = load_plan("abc", settings=settings)
        assert data is not None
        assert data["plan_id"] == "abc"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        assert load_plan("nonexistent", settings=settings) is None

    def test_returns_none_for_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt files should return None, not crash."""
        (tmp_path / "plan-bad.json").write_text("not valid json{{{")
        settings = _test_settings(tmp_path)
        assert load_plan("bad", settings=settings) is None


class TestListRecentPlans:
    def test_lists_plans(self, tmp_path: Path) -> None:
        for i in range(3):
            (tmp_path / f"plan-{i}.json").write_text(
                json.dumps(
                    {
                        "plan_id": str(i),
                        "timestamp": f"2025-01-0{i + 1}T00:00:00+00:00",
                        "change_description": f"Change {i}",
                        "state": {"status": "proposed"},
                        "plan": {"risk_level": "LOW", "estimated_effort": "S"},
                    }
                )
            )
        settings = _test_settings(tmp_path)
        results = list_recent_plans(limit=10, settings=settings)
        assert len(results) == 3

    def test_empty_directory(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        assert list_recent_plans(settings=settings) == []

    def test_respects_limit(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"plan-{i}.json").write_text(
                json.dumps(
                    {
                        "plan_id": str(i),
                        "timestamp": f"2025-01-0{i + 1}T00:00:00+00:00",
                        "change_description": f"Change {i}",
                        "state": {"status": "proposed"},
                        "plan": {},
                    }
                )
            )
        settings = _test_settings(tmp_path)
        results = list_recent_plans(limit=2, settings=settings)
        assert len(results) == 2

    def test_ordered_by_timestamp_descending(self, tmp_path: Path) -> None:
        """Plans should be returned newest-first based on their JSON timestamp."""
        plans = [
            ("plan-a.json", "2025-06-01T10:00:00+00:00", "Oldest"),
            ("plan-b.json", "2025-06-03T10:00:00+00:00", "Newest"),
            ("plan-c.json", "2025-06-02T10:00:00+00:00", "Middle"),
        ]
        for filename, ts, desc in plans:
            (tmp_path / filename).write_text(
                json.dumps(
                    {
                        "plan_id": filename.replace("plan-", "").replace(".json", ""),
                        "timestamp": ts,
                        "change_description": desc,
                        "state": {"status": "proposed"},
                        "plan": {},
                    }
                )
            )
        settings = _test_settings(tmp_path)
        results = list_recent_plans(limit=10, settings=settings)
        descriptions = [r["change_description"] for r in results]
        assert descriptions == ["Newest", "Middle", "Oldest"]


class TestDeletePlan:
    def test_deletes_existing(self, tmp_path: Path) -> None:
        (tmp_path / "plan-del.json").write_text("{}")
        settings = _test_settings(tmp_path)
        assert delete_plan("del", settings=settings) is True
        assert not (tmp_path / "plan-del.json").exists()

    def test_returns_false_for_missing(self, tmp_path: Path) -> None:
        settings = _test_settings(tmp_path)
        assert delete_plan("nope", settings=settings) is False
