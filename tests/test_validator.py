from __future__ import annotations

from agentfix.config import GuardrailSettings, ValidationSettings
from agentfix.incident_ingest import IncidentIngestor
from agentfix.repo_context import RepoContextCollector
from agentfix.validator import Validator


def test_validator_runs_py_compile_and_pytest(temp_repo, fixtures_root) -> None:
    repo = temp_repo("type_error_repo")
    (repo / "app" / "formatter.py").write_text(
        "from __future__ import annotations\n\n\n"
        "def label_count(prefix, count):\n"
        "    return prefix + str(count)\n",
        encoding="utf-8",
    )

    incident = IncidentIngestor().from_file(fixtures_root / "logs" / "type_error.log")
    repo_context = RepoContextCollector(GuardrailSettings()).collect(repo, incident)
    result = Validator().validate(
        repo,
        changed_files=["app/formatter.py"],
        repo_context=repo_context,
        settings=ValidationSettings(),
    )

    assert result.syntax_check is True
    assert result.tests_passed is True
    assert result.tests_executed is True
    assert result.tests_skipped_reason is None
    assert any("py_compile" in command.command for command in result.commands)


def test_validator_reports_explicit_test_skip(temp_repo, fixtures_root) -> None:
    repo = temp_repo("type_error_repo")
    (repo / "app" / "formatter.py").write_text(
        "from __future__ import annotations\n\n\n"
        "def label_count(prefix, count):\n"
        "    return prefix + str(count)\n",
        encoding="utf-8",
    )

    incident = IncidentIngestor().from_file(fixtures_root / "logs" / "type_error.log")
    repo_context = RepoContextCollector(GuardrailSettings()).collect(repo, incident)
    result = Validator().validate(
        repo,
        changed_files=["app/formatter.py"],
        repo_context=repo_context,
        settings=ValidationSettings(test_commands=[]),
    )

    assert result.syntax_check is True
    assert result.tests_passed is None
    assert result.tests_executed is False
    assert result.tests_skipped_reason == "Functional tests were skipped by validation.test_commands configuration."
    assert len(result.commands) == 1
