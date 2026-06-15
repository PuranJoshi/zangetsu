"""Tests for the file approval flow -- discover paths then read approved only.

Tests three safety layers:
1. Dotfiles (.env, .zshrc) are NEVER discovered (except safe ones like .gitignore)
2. Credential files (application.live.yaml, secrets.json) are flagged as sensitive
3. Only explicitly approved files are read
"""

from pathlib import Path

from code_council.context import (
    discover_relevant_paths,
    is_dotfile,
    is_potential_credential_file,
    read_approved_files,
)


class TestDotfileDetection:
    def test_env_is_dotfile(self) -> None:
        assert is_dotfile(".env")

    def test_zshrc_is_dotfile(self) -> None:
        assert is_dotfile(".zshrc")

    def test_npmrc_is_dotfile(self) -> None:
        assert is_dotfile(".npmrc")

    def test_gitignore_is_safe(self) -> None:
        """.gitignore is explicitly allowed -- it's just patterns, no secrets."""
        assert not is_dotfile(".gitignore")

    def test_dockerignore_is_safe(self) -> None:
        assert not is_dotfile(".dockerignore")

    def test_editorconfig_is_safe(self) -> None:
        assert not is_dotfile(".editorconfig")

    def test_normal_file_is_not_dotfile(self) -> None:
        assert not is_dotfile("main.py")

    def test_env_local_is_dotfile(self) -> None:
        assert is_dotfile(".env.local")


class TestCredentialDetection:
    def test_application_live_yaml(self) -> None:
        """Kotlin/Spring production configs often have credentials."""
        assert is_potential_credential_file("application.live.yaml")

    def test_application_prod_yaml(self) -> None:
        assert is_potential_credential_file("application.prod.yaml")

    def test_secrets_json(self) -> None:
        assert is_potential_credential_file("secrets.json")

    def test_private_key_pem(self) -> None:
        assert is_potential_credential_file("private_key.pem")

    def test_service_account_json(self) -> None:
        assert is_potential_credential_file("service_account.json")

    def test_keystore_jks(self) -> None:
        assert is_potential_credential_file("my.keystore.jks")

    def test_normal_file_not_flagged(self) -> None:
        assert not is_potential_credential_file("main.py")

    def test_application_yaml_not_flagged(self) -> None:
        """Plain application.yaml is fine -- it's the .live/.prod that's risky."""
        assert not is_potential_credential_file("application.yaml")

    def test_config_production_json(self) -> None:
        assert is_potential_credential_file("config.production.json")


class TestDiscoverRelevantPaths:
    def test_returns_path_score_sensitive_tuples(self, tmp_path: Path) -> None:
        """Each result is (path, score, is_sensitive)."""
        (tmp_path / "auth.py").write_text("def login(): pass")
        result = discover_relevant_paths(tmp_path, "authentication")
        assert len(result) > 0
        path, score, sensitive = result[0]
        assert isinstance(path, str)
        assert isinstance(score, float)
        assert isinstance(sensitive, bool)
        assert "auth" in path

    def test_never_discovers_dotfiles(self, tmp_path: Path) -> None:
        """Dotfiles must never appear in results, even if keywords match."""
        (tmp_path / ".env").write_text("AUTH_SECRET=abc123")
        (tmp_path / "auth.py").write_text("def login(): pass")
        result = discover_relevant_paths(tmp_path, "auth")
        paths = [p for p, _, _ in result]
        assert ".env" not in paths
        assert any("auth.py" in p for p in paths)

    def test_gitignore_can_be_discovered(self, tmp_path: Path) -> None:
        """.gitignore is a safe dotfile -- it should be discoverable."""
        (tmp_path / ".gitignore").write_text("node_modules\n*.pyc\n")
        result = discover_relevant_paths(tmp_path, "gitignore")
        paths = [p for p, _, _ in result]
        assert ".gitignore" in paths

    def test_flags_credential_files_as_sensitive(self, tmp_path: Path) -> None:
        (tmp_path / "secrets.json").write_text('{"api_key": "xxx"}')
        result = discover_relevant_paths(tmp_path, "secrets")
        assert len(result) > 0
        _, _, sensitive = result[0]
        assert sensitive is True

    def test_normal_files_not_sensitive(self, tmp_path: Path) -> None:
        (tmp_path / "auth.py").write_text("def login(): pass")
        result = discover_relevant_paths(tmp_path, "auth")
        assert len(result) > 0
        _, _, sensitive = result[0]
        assert sensitive is False

    def test_sorted_by_score(self, tmp_path: Path) -> None:
        (tmp_path / "auth.py").write_text("x")
        (tmp_path / "auth_test.py").write_text("x")
        (tmp_path / "utils.py").write_text("x")
        result = discover_relevant_paths(tmp_path, "auth")
        scores = [s for _, s, _ in result]
        assert scores == sorted(scores, reverse=True)

    def test_skips_ignored_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "auth.js").write_text("x")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "auth.py").write_text("x")
        result = discover_relevant_paths(tmp_path, "auth")
        paths = [p for p, _, _ in result]
        assert not any("node_modules" in p for p in paths)

    def test_empty_description_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("x")
        result = discover_relevant_paths(tmp_path, "")
        assert result == []


class TestReadApprovedFiles:
    def test_reads_only_approved(self, tmp_path: Path) -> None:
        (tmp_path / "approved.py").write_text("approved content")
        (tmp_path / "secret.py").write_text("SECRET_KEY=abc123")
        result = read_approved_files(tmp_path, ["approved.py"])
        assert "approved.py" in result
        assert "secret.py" not in result
        assert result["approved.py"] == "approved content"

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        result = read_approved_files(tmp_path, ["nonexistent.py"])
        assert result == {}

    def test_empty_approval_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "file.py").write_text("x")
        result = read_approved_files(tmp_path, [])
        assert result == {}
