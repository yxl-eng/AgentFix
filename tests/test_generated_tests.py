from __future__ import annotations

from pathlib import Path

from patchpilot.config import AppConfig, TargetSettings, ValidationSettings
from patchpilot.generated_tests import FrameworkDetector, GeneratedTestRunner, GeneratedTestValidator
from patchpilot.incident_ingest import IncidentIngestor
from patchpilot.models import (
    AnalysisResult,
    FilePatch,
    GeneratedTestProposal,
    RepairIntent,
    ValidationCommandResult,
)
from patchpilot.patch_engine import PatchEngine
from patchpilot.publisher import GitHubPublisher
from patchpilot.repair_orchestrator import RepairOrchestrator
from patchpilot.repo_context import RepoContextCollector
from patchpilot.services.analysis import AnalysisAgent
from patchpilot.services.patching import PatchAgent
from patchpilot.generated_tests import GeneratedTestAgent
from patchpilot.validator import Validator
from tests.helpers import StaticProvider


def test_framework_detector_detects_python_unittest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (tests / "test_service.py").write_text(
        "import unittest\n\nclass ServiceTests(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
        encoding="utf-8",
    )

    result = FrameworkDetector().detect(repo)

    assert result.framework == "python-unittest"


def test_framework_detector_detects_node_jest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"devDependencies":{"jest":"latest"}}', encoding="utf-8")

    result = FrameworkDetector().detect(repo)

    assert result.framework == "node-jest"


def test_generated_test_runner_builds_framework_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = GeneratedTestRunner()
    proposal = GeneratedTestProposal(test_path="tests/test_patchpilot_bug.py", test_name="test_bug")

    command = runner.build_command(
        repo,
        proposal,
        FrameworkDetector()._explicit("pytest"),
        ValidationSettings(python_executable="python"),
    )

    assert isinstance(command, list)
    assert command[1:] == ["-m", "pytest", "tests/test_patchpilot_bug.py"]


def test_generated_test_runner_normalizes_model_pytest_command(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = GeneratedTestRunner()
    proposal = GeneratedTestProposal(
        test_path="tests/test_patchpilot_bug.py",
        test_name="test_bug",
        run_command=["pytest", "tests/test_patchpilot_bug.py", "-v"],
    )

    command = runner.build_command(
        repo,
        proposal,
        FrameworkDetector()._explicit("pytest"),
        ValidationSettings(python_executable="python"),
    )

    assert command == ["python", "-m", "pytest", "tests/test_patchpilot_bug.py", "-v"]


def test_generated_test_repair_filter_excludes_existing_tests() -> None:
    config = AppConfig()
    target = TargetSettings(repo_path="repo")
    orchestrator = RepairOrchestrator(
        config=config,
        ingestor=IncidentIngestor(),
        collector=RepoContextCollector(config.guardrails),
        analyzer=AnalysisAgent(StaticProvider([]), config),
        patch_agent=PatchAgent(StaticProvider([]), config),
        patch_engine=PatchEngine(),
        validator=Validator(),
        publisher=GitHubPublisher(config.github),
    )
    analysis = AnalysisResult(
        root_cause_summary="unsafe permissions lookup",
        confidence=0.9,
        candidate_targets=[
            RepairIntent(
                path="app/services.py",
                rationale="business logic",
                confidence=0.99,
                change_summary="fix lookup",
            ),
            RepairIntent(
                path="tests/test_orders.py",
                rationale="existing tests",
                confidence=0.4,
                change_summary="add coverage",
            ),
        ],
    )

    filtered = orchestrator._analysis_for_repair_patch(analysis, target)

    assert [item.path for item in filtered.candidate_targets] == ["app/services.py"]


def test_generated_test_legacy_fallback_maps_to_failure_policy() -> None:
    target = TargetSettings(repo_path="repo", generated_tests={"fallback_to_v2_on_failure": False})

    assert target.generated_tests.failure_policy == "needs_human_verification"

    target = TargetSettings(repo_path="repo", generated_tests={"fallback_to_v2_on_failure": True})

    assert target.generated_tests.failure_policy == "continue_existing_validation"


def test_generated_test_validator_rejects_infrastructure_failures() -> None:
    incident = IncidentIngestor().parse_log("Traceback\nTypeError: boom")
    result = ValidationCommandResult(
        command="python -m pytest tests/test_generated.py",
        returncode=1,
        stderr="ModuleNotFoundError: No module named 'app'",
    )

    assert GeneratedTestValidator().is_prefix_failure_related(result, incident) is False


def test_orchestrator_commits_stable_generated_test(temp_repo, fixtures_root, tmp_path) -> None:
    repo = temp_repo("none_attr_repo")
    config = AppConfig()
    config.runtime.artifact_root = str(tmp_path / "artifacts")
    target = TargetSettings(repo_path=str(repo), base_branch="main")

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
                        change_summary="Return None when user is missing.",
                    )
                ],
                repair_plan=["Guard the attribute access before dereferencing profile."],
                validation_focus=["Verify the None case and the happy path test."],
            ),
            GeneratedTestProposal(
                summary="Cover missing user regression.",
                framework="python-pytest",
                test_path="tests/test_patchpilot_generated.py",
                test_name="test_patchpilot_missing_user_returns_none",
                updated_content=(
                    "from __future__ import annotations\n\n"
                    "from app.service import get_user_email\n\n\n"
                    "def test_patchpilot_missing_user_returns_none() -> None:\n"
                    "    assert get_user_email(None) is None\n"
                ),
                expected_behavior="Missing user should return None.",
                confidence=0.9,
            ),
            {
                "summary": "Guard None before accessing profile.",
                "patches": [
                    {
                        "path": "app/service.py",
                        "reason": "Prevent NoneType attribute access.",
                        "updated_content": (
                            "from __future__ import annotations\n\n\n"
                            "def get_user_email(user):\n"
                            "    if user is None or getattr(user, 'profile', None) is None:\n"
                            "        return None\n"
                            "    return user.profile.email\n"
                        ),
                    }
                ],
                "validation_notes": ["Run service tests."],
            },
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
        generated_test_agent=GeneratedTestAgent(provider, config),
    )

    result = orchestrator.run(
        repo,
        fixtures_root / "logs" / "none_attr.log",
        publish=False,
        target_config=target,
    )

    assert result.status == "fixed"
    assert result.generated_test is not None
    assert result.generated_test.prefix_failed is True
    assert result.generated_test.postfix_passed is True
    assert result.generated_test.committed is True
    assert "tests/test_patchpilot_generated.py" in result.changed_files
    assert "app/service.py" in result.changed_files


def test_orchestrator_discards_unstable_generated_test_when_existing_validation_passes(
    temp_repo,
    fixtures_root,
    tmp_path,
) -> None:
    repo = temp_repo("none_attr_repo")
    config = AppConfig()
    config.runtime.artifact_root = str(tmp_path / "artifacts")
    target = TargetSettings(repo_path=str(repo), base_branch="main")
    target.generated_tests.failure_policy = "continue_existing_validation"

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
                        change_summary="Return None when user is missing.",
                    )
                ],
                repair_plan=["Guard the attribute access before dereferencing profile."],
                validation_focus=["Verify the None case and the happy path test."],
            ),
            GeneratedTestProposal(
                summary="Cover missing user regression but includes an unstable extra assertion.",
                framework="python-pytest",
                test_path="tests/test_patchpilot_generated.py",
                test_name="test_patchpilot_missing_user_returns_none",
                updated_content=(
                    "from __future__ import annotations\n\n"
                    "from app.service import get_user_email\n\n\n"
                    "class Profile:\n"
                    "    def __init__(self, email: str) -> None:\n"
                    "        self.email = email\n\n\n"
                    "class User:\n"
                    "    def __init__(self, email: str) -> None:\n"
                    "        self.profile = Profile(email)\n\n\n"
                    "def test_patchpilot_missing_user_returns_none() -> None:\n"
                    "    assert get_user_email(None) is None\n\n\n"
                    "def test_patchpilot_unrelated_assertion_is_not_stable() -> None:\n"
                    "    assert get_user_email(User('dev@example.com')) == 'wrong@example.com'\n"
                ),
                expected_behavior="Missing user should return None.",
                confidence=0.7,
            ),
            {
                "summary": "Guard None before accessing profile.",
                "patches": [
                    {
                        "path": "app/service.py",
                        "reason": "Prevent NoneType attribute access.",
                        "updated_content": (
                            "from __future__ import annotations\n\n\n"
                            "def get_user_email(user):\n"
                            "    if user is None or getattr(user, 'profile', None) is None:\n"
                            "        return None\n"
                            "    return user.profile.email\n"
                        ),
                    }
                ],
                "validation_notes": ["Run service tests."],
            },
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
        generated_test_agent=GeneratedTestAgent(provider, config),
    )

    result = orchestrator.run(
        repo,
        fixtures_root / "logs" / "none_attr.log",
        publish=False,
        target_config=target,
    )

    assert result.status == "fixed"
    assert result.generated_test is not None
    assert result.generated_test.prefix_failed is True
    assert result.generated_test.postfix_passed is False
    assert result.generated_test.committed is False
    assert result.generated_test.fallback_reason is not None
    assert result.changed_files == ["app/service.py"]
    assert "tests/test_patchpilot_generated.py" not in result.changed_files


def test_generated_test_failure_policy_can_require_human_verification(
    temp_repo,
    fixtures_root,
    tmp_path,
) -> None:
    repo = temp_repo("none_attr_repo")
    config = AppConfig()
    config.runtime.artifact_root = str(tmp_path / "artifacts")
    config.runtime.max_repair_attempts = 1
    target = TargetSettings(repo_path=str(repo), base_branch="main")
    target.generated_tests.failure_policy = "needs_human_verification"

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
                        change_summary="Return None when user is missing.",
                    )
                ],
                repair_plan=["Guard the attribute access before dereferencing profile."],
            ),
            GeneratedTestProposal(
                summary="Cover missing user regression but keep an unstable assertion.",
                framework="python-pytest",
                test_path="tests/test_patchpilot_generated.py",
                test_name="test_patchpilot_missing_user_returns_none",
                updated_content=(
                    "from __future__ import annotations\n\n"
                    "from app.service import get_user_email\n\n\n"
                    "class Profile:\n"
                    "    def __init__(self, email: str) -> None:\n"
                    "        self.email = email\n\n\n"
                    "class User:\n"
                    "    def __init__(self, email: str) -> None:\n"
                    "        self.profile = Profile(email)\n\n\n"
                    "def test_patchpilot_missing_user_returns_none() -> None:\n"
                    "    assert get_user_email(None) is None\n\n\n"
                    "def test_patchpilot_unstable_assertion() -> None:\n"
                    "    assert get_user_email(User('dev@example.com')) == 'wrong@example.com'\n"
                ),
                expected_behavior="Missing user should return None.",
                confidence=0.7,
            ),
            {
                "summary": "Guard None before accessing profile.",
                "patches": [
                    {
                        "path": "app/service.py",
                        "reason": "Prevent NoneType attribute access.",
                        "updated_content": (
                            "from __future__ import annotations\n\n\n"
                            "def get_user_email(user):\n"
                            "    if user is None or getattr(user, 'profile', None) is None:\n"
                            "        return None\n"
                            "    return user.profile.email\n"
                        ),
                    }
                ],
            },
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
        generated_test_agent=GeneratedTestAgent(provider, config),
    )

    result = orchestrator.run(
        repo,
        fixtures_root / "logs" / "none_attr.log",
        publish=False,
        target_config=target,
    )

    assert result.status == "needs_human_verification"
    assert result.generated_test is not None
    assert result.generated_test.postfix_passed is False
