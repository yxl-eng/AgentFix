from __future__ import annotations

from patchpilot.config import AppConfig
from patchpilot.incident_ingest import IncidentIngestor
from patchpilot.models import AnalysisResult, FilePatch, PatchProposal, RepairIntent
from patchpilot.patch_engine import PatchEngine
from patchpilot.publisher import GitHubPublisher
from patchpilot.repair_orchestrator import RepairOrchestrator
from patchpilot.repo_context import RepoContextCollector
from patchpilot.services.analysis import AnalysisAgent
from patchpilot.services.patching import PatchAgent
from patchpilot.validator import Validator
from tests.helpers import StaticProvider


def test_orchestrator_runs_end_to_end_with_fake_provider(temp_repo, fixtures_root, tmp_path) -> None:
    repo = temp_repo("none_attr_repo")
    config = AppConfig()
    config.runtime.artifact_root = str(tmp_path / "artifacts")

    provider = StaticProvider(
        [
            AnalysisResult(
                root_cause_summary="The code dereferences user.profile even when user is None.",
                confidence=0.93,
                candidate_targets=[
                    RepairIntent(
                        path="app/service.py",
                        rationale="Traceback points directly to this file.",
                        confidence=0.93,
                        change_summary="Return None when user or profile is missing.",
                    )
                ],
                repair_plan=["Guard the attribute access before dereferencing profile."],
                validation_focus=["Verify the None case and the happy path test."],
            ),
            PatchProposal(
                summary="Guard None before accessing profile.",
                patches=[
                    FilePatch(
                        path="app/service.py",
                        reason="Prevent NoneType attribute access.",
                        updated_content=(
                            "from __future__ import annotations\n\n\n"
                            "def get_user_email(user):\n"
                            "    if user is None or getattr(user, 'profile', None) is None:\n"
                            "        return None\n"
                            "    return user.profile.email\n"
                        ),
                    )
                ],
                validation_notes=["Run service tests."],
            ),
        ]
    )

    orchestrator = RepairOrchestrator(
        config=config,
        ingestor=IncidentIngestor(),
        collector=RepoContextCollector(config.guardrails),
        analyzer=AnalysisAgent(provider, config),
        patch_agent=PatchAgent(provider, config),
        patch_engine=PatchEngine(),
        validator=Validator(),
        publisher=GitHubPublisher(config.github),
    )

    result = orchestrator.run(
        repo,
        fixtures_root / "logs" / "none_attr.log",
        publish=False,
    )

    assert result.status == "fixed"
    assert result.syntax_check is True
    assert result.changed_files == ["app/service.py"]
    assert any("pytest" in command for command in result.tests_run)
    assert result.repair_iterations
