from __future__ import annotations

import re

from patchpilot.agent_server import AgentProcessor
from patchpilot.config import AppConfig, RecordsSettings, TargetSettings
from patchpilot.event_state import EventStateStore
from patchpilot.models import RepairResult, ValidationCommandResult, ValidationResult
from patchpilot.repair_records import RepairRecordWriter


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = 0

    def run_incident(self, repo_path, incident, *, base_branch="main", publish=True, target_config=None):
        self.calls += 1
        return RepairResult(
            root_cause_summary="Fixed a service bug.",
            changed_files=["src/app.ts"],
            syntax_check=True,
            tests_run=["npm test"],
            pr_url="https://github.com/org/repo/pull/1",
            status="fixed",
            validation=ValidationResult(
                syntax_check=True,
                tests_passed=True,
                tests_executed=True,
                commands=[ValidationCommandResult(command="npm test", returncode=0)],
            ),
            branch="patchpilot/test",
        )


class FakeNotifier:
    def notify_repair(self, record):
        return True, "sent"


def _processor(tmp_path):
    repo = tmp_path / "service"
    repo.mkdir()
    config = AppConfig(
        targets={
            "svc": TargetSettings(
                repo_full_name="org/repo",
                repo_path=str(repo),
                base_branch="main",
            )
        },
        records=RecordsSettings(root="records", auto_commit=False),
    )
    orchestrator = FakeOrchestrator()
    processor = AgentProcessor(
        config=config,
        orchestrator=orchestrator,
        state_store=EventStateStore(tmp_path / "state" / "events.sqlite3"),
        record_writer=RepairRecordWriter(config.records, project_root=tmp_path),
        notifier=FakeNotifier(),
        project_root=tmp_path,
    )
    return processor, orchestrator


def test_incident_webhook_rejects_repo_paths(tmp_path) -> None:
    processor, _ = _processor(tmp_path)

    response = processor.handle_incident_payload(
        {"target": "svc", "repo_path": "C:/unsafe", "log_text": "TypeError: boom"}
    )

    assert response["status"] == "rejected"


def test_incident_webhook_processes_once_and_records_tool_calls(tmp_path) -> None:
    processor, orchestrator = _processor(tmp_path)
    payload = {"target": "svc", "incident_id": "inc-1", "log_text": "TypeError: boom"}

    first = processor.handle_incident_payload(payload)
    second = processor.handle_incident_payload(payload)

    assert first["status"] == "fixed"
    assert second["status"] == "duplicate"
    assert orchestrator.calls == 1
    tool_names = [tool["name"] for tool in first["record"]["tool_calls"]]
    assert "Read Log" in tool_names
    assert "Read Code" in tool_names
    assert "Run Verification" in tool_names
    assert "Git Commit/PR" in tool_names
    assert "Record Repair" in tool_names
    assert "Notify Feishu" in tool_names
    assert "Incident Planner" in tool_names
    assert first["record"]["disposition"] == "repair_attempt"


def test_incident_webhook_without_id_uses_service_timestamp(tmp_path) -> None:
    processor, _ = _processor(tmp_path)

    response = processor.handle_incident_payload({"target": "svc", "log_text": "Traceback\nTypeError: boom"})

    assert response["status"] == "fixed"
    assert re.match(r"svc-\d{8}-\d{6}-\d{3}$", response["record"]["incident_id"])


def test_github_webhook_only_processes_bug_issue_for_configured_repo(tmp_path) -> None:
    processor, orchestrator = _processor(tmp_path)
    payload = {
        "action": "opened",
        "repository": {"full_name": "org/repo"},
        "issue": {
            "number": 12,
            "title": "Bug",
            "body": "TypeError: boom",
            "labels": [{"name": "bug"}],
            "html_url": "https://github.com/org/repo/issues/12",
        },
    }

    response = processor.handle_github_payload(payload, headers={"X-GitHub-Event": "issues"})

    assert response["status"] == "fixed"
    assert orchestrator.calls == 1


def test_github_webhook_ignores_non_bug_issue(tmp_path) -> None:
    processor, orchestrator = _processor(tmp_path)
    payload = {
        "action": "opened",
        "repository": {"full_name": "org/repo"},
        "issue": {"number": 12, "body": "broken", "labels": [{"name": "question"}]},
    }

    response = processor.handle_github_payload(payload, headers={"X-GitHub-Event": "issues"})

    assert response["status"] == "ignored"
    assert orchestrator.calls == 0


def test_planner_ignores_benign_error_without_repair(tmp_path) -> None:
    processor, orchestrator = _processor(tmp_path)

    response = processor.handle_incident_payload(
        {
            "target": "svc",
            "incident_id": "benign-1",
            "log_text": "level=error http 404 expected business rejection for missing optional avatar",
        }
    )

    assert response["status"] == "ignored"
    assert orchestrator.calls == 0
    assert response["record"]["root_cause_type"] == "benign_log"


def test_planner_reports_environment_failure_without_repair(tmp_path) -> None:
    processor, orchestrator = _processor(tmp_path)

    response = processor.handle_incident_payload(
        {
            "target": "svc",
            "incident_id": "env-1",
            "log_text": "Traceback\nConnection refused while connecting to redis://localhost:6379",
        }
    )

    assert response["status"] == "needs_manual_intervention"
    assert orchestrator.calls == 0
    assert response["record"]["human_action_required"] is True
    assert response["record"]["root_cause_type"] == "external_dependency"
