from __future__ import annotations

from agentfix.config import GitHubSettings
from agentfix.models import AnalysisResult, AppliedPatch, Incident, RepairIntent, ValidationCommandResult, ValidationResult
from agentfix.publisher import GitHubPublisher


def test_publisher_builds_branch_and_body() -> None:
    publisher = GitHubPublisher(GitHubSettings())
    incident = Incident(
        service_name="user-api",
        environment="prod",
        log_text="traceback",
        exception_type="AttributeError",
        exception_message="'NoneType' object has no attribute 'profile'",
        incident_id="inc-1001",
    )
    analysis = AnalysisResult(
        root_cause_summary="The user object can be None before dereferencing profile.",
        confidence=0.91,
        candidate_targets=[
            RepairIntent(
                path="app/service.py",
                rationale="Traceback points here.",
                confidence=0.91,
                change_summary="Guard against a missing user.",
            )
        ],
    )
    applied = AppliedPatch(
        changed_files=["app/service.py"],
        diff_text="--- app/service.py\n+++ app/service.py\n",
        patch_line_count=2,
        summary="Guard None access.",
        workspace_path="C:/repo",
    )
    validation = ValidationResult(
        syntax_check=True,
        tests_passed=True,
        commands=[ValidationCommandResult(command="python -m py_compile app/service.py", returncode=0)],
    )

    branch = publisher.build_branch_name(incident)
    body = publisher.build_pr_body(incident, analysis, applied, validation)

    assert branch == "agentfix/inc-1001/attributeerror"
    assert "## Error Summary" in body
    assert "`app/service.py`" in body
    assert "python -m py_compile app/service.py" in body
