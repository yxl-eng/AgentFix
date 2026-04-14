from __future__ import annotations

from agentfix.config import AppConfig
from agentfix.incident_ingest import IncidentIngestor
from agentfix.models import AnalysisResult, FilePatch, PatchProposal, RepairIntent
from agentfix.patch_engine import PatchEngine
from agentfix.publisher import GitHubPublisher
from agentfix.repair_orchestrator import RepairOrchestrator
from agentfix.repo_context import RepoContextCollector
from agentfix.services.analysis import AnalysisAgent
from agentfix.services.patching import PatchAgent
from agentfix.validator import Validator
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

    assert result.status == "validated"
    assert result.syntax_check is True
    assert result.changed_files == ["app/service.py"]
    assert any("pytest" in command for command in result.tests_run)
