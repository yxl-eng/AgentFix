from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from agentfix.config import GuardrailSettings, TargetSettings, ValidationSettings, VerificationRequestSettings
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
    assert result.tests_skipped_reason == "validation.test_commands 配置为空，因此跳过功能测试。"
    assert len(result.commands) == 1


def test_validator_runs_service_healthcheck_and_verification(tmp_path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/health"
    repo = tmp_path / "repo"
    repo.mkdir()
    incident = IncidentIngestor().placeholder("service-healthcheck")
    repo_context = RepoContextCollector(GuardrailSettings()).collect(repo, incident)

    try:
        result = Validator().validate(
            repo,
            changed_files=[],
            repo_context=repo_context,
            settings=ValidationSettings(test_commands=[]),
            target_config=TargetSettings(
                repo_path=str(repo),
                healthcheck_url=url,
                verification_requests=[VerificationRequestSettings(method="GET", url=url, expected_status=200)],
            ),
            incident=incident,
        )
    finally:
        server.shutdown()

    assert result.tests_executed is True
    assert result.tests_passed is True
    assert any(command.command.startswith("healthcheck") for command in result.commands)
    assert any(command.command.startswith("GET") for command in result.commands)
