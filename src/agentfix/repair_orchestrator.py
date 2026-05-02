from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agentfix.config import AppConfig, GuardrailSettings, TargetSettings
from agentfix.generated_tests import (
    FrameworkDetector,
    GeneratedTestAgent,
    GeneratedTestRunner,
    GeneratedTestValidator,
)
from agentfix.incident_ingest import IncidentIngestor
from agentfix.models import (
    AppliedPatch,
    FilePatch,
    GeneratedTestProposal,
    GeneratedTestResult,
    Incident,
    PatchProposal,
    RepairResult,
    ValidationResult,
)
from agentfix.patch_engine import PatchEngine, PatchGuardrailError
from agentfix.publisher import GitHubPublisher, PublisherError
from agentfix.repo_context import RepoContextCollector
from agentfix.services.analysis import AnalysisAgent
from agentfix.services.patching import PatchAgent
from agentfix.validator import Validator


class RepairOrchestrator:
    def __init__(
        self,
        *,
        config: AppConfig,
        ingestor: IncidentIngestor,
        collector: RepoContextCollector,
        analyzer: AnalysisAgent,
        patch_agent: PatchAgent,
        patch_engine: PatchEngine,
        validator: Validator,
        publisher: GitHubPublisher,
        generated_test_agent: GeneratedTestAgent | None = None,
        framework_detector: FrameworkDetector | None = None,
        generated_test_runner: GeneratedTestRunner | None = None,
        generated_test_validator: GeneratedTestValidator | None = None,
    ) -> None:
        self.config = config
        self.ingestor = ingestor
        self.collector = collector
        self.analyzer = analyzer
        self.patch_agent = patch_agent
        self.patch_engine = patch_engine
        self.validator = validator
        self.publisher = publisher
        self.generated_test_agent = generated_test_agent
        self.framework_detector = framework_detector or FrameworkDetector()
        self.generated_test_runner = generated_test_runner or GeneratedTestRunner()
        self.generated_test_validator = generated_test_validator or GeneratedTestValidator()

    def analyze(self, repo_path: str | Path, log_file: str | Path, base_branch: str = "main") -> dict[str, object]:
        incident = self.ingestor.from_file(log_file)
        repo_context = self.collector.collect(repo_path, incident, base_branch)
        analysis = self.analyzer.analyze(incident, repo_context)
        return {
            "incident": incident.model_dump(mode="json"),
            "analysis": analysis.model_dump(mode="json"),
            "candidates": [item.model_dump(mode="json") for item in repo_context.candidate_files],
        }

    def validate_existing(
        self,
        repo_path: str | Path,
        changed_files: list[str],
        log_file: str | Path | None = None,
        base_branch: str = "main",
        target_config: TargetSettings | None = None,
    ) -> ValidationResult:
        incident = self.ingestor.from_file(log_file) if log_file else self.ingestor.placeholder()
        repo_context = self.collector.collect(repo_path, incident, base_branch)
        return self.validator.validate(
            repo_path,
            changed_files,
            repo_context,
            self.config.validation,
            target_config=target_config,
            incident=incident,
        )

    def run(
        self,
        repo_path: str | Path,
        log_file: str | Path,
        *,
        base_branch: str = "main",
        publish: bool = True,
        target_config: TargetSettings | None = None,
    ) -> RepairResult:
        source_repo = Path(repo_path).resolve()
        incident = self.ingestor.from_file(log_file)
        return self.run_incident(
            source_repo,
            incident,
            base_branch=base_branch,
            publish=publish,
            target_config=target_config,
        )

    def run_incident(
        self,
        repo_path: str | Path,
        incident: Incident,
        *,
        base_branch: str = "main",
        publish: bool = True,
        target_config: TargetSettings | None = None,
    ) -> RepairResult:
        source_repo = Path(repo_path).resolve()
        artifact_dir = self._create_artifact_dir(incident)
        repo_context = self.collector.collect(source_repo, incident, base_branch)
        analysis = self.analyzer.analyze(incident, repo_context)

        self._write_json(artifact_dir / "incident.json", incident.model_dump(mode="json"))
        self._write_json(artifact_dir / "analysis.json", analysis.model_dump(mode="json"))

        if analysis.confidence < self.config.guardrails.min_confidence:
            result = RepairResult(
                root_cause_summary=analysis.root_cause_summary,
                status="needs_manual_intervention",
                analysis=analysis,
                artifact_dir=str(artifact_dir),
                failure_reason="Analysis confidence below configured threshold.",
            )
            self._write_result_bundle(artifact_dir, result)
            return result

        feedback: list[str] = []
        last_validation: ValidationResult | None = None
        last_failure: str | None = None

        for attempt in range(1, self.config.runtime.max_repair_attempts + 1):
            with self._temporary_workspace(source_repo) as workspace:
                attempt_context = self.collector.collect(workspace, incident, base_branch)
                try:
                    generated_result, generated_patch = self._prepare_generated_test(
                        workspace=workspace,
                        incident=incident,
                        analysis=analysis,
                        repo_context=attempt_context,
                        target_config=target_config,
                        artifact_dir=artifact_dir,
                        attempt=attempt,
                        feedback=feedback,
                    )
                    if self._generated_test_requires_failure(generated_result, target_config):
                        validation = self._generated_test_failure_validation(generated_result)
                        last_validation = validation
                        self._write_json(
                            artifact_dir / f"attempt-{attempt}-generated-test-validation.json",
                            validation.model_dump(mode="json"),
                        )
                        feedback = validation.failure_summary or ["Generated regression test could not be verified."]
                        last_failure = "; ".join(feedback)
                        continue

                    repair_analysis = self._analysis_for_repair_patch(analysis, target_config)
                    proposal = self.patch_agent.propose(incident, repair_analysis, attempt_context, feedback=feedback)
                    self._write_json(
                        artifact_dir / f"attempt-{attempt}-proposal.json",
                        proposal.model_dump(mode="json"),
                    )
                    allowed_paths = [
                        target.path
                        for target in repair_analysis.candidate_targets[: self.config.guardrails.max_changed_files]
                    ]
                    applied_patch = self.patch_engine.apply(
                        workspace,
                        proposal,
                        allowed_paths=allowed_paths,
                        guardrails=self.config.guardrails,
                    )
                    if not applied_patch.changed_files:
                        raise PatchGuardrailError("Patch proposal produced no file changes.")

                    if generated_result is not None and generated_patch is not None:
                        post_fix_result = self.generated_test_runner.run(
                            workspace,
                            GeneratedTestProposal(
                                test_path=generated_result.test_path,
                                test_name=generated_result.test_name,
                                run_command=generated_result.run_command,
                            ),
                            self.framework_detector.detect(workspace, target_config),
                            self.config.validation,
                        )
                        generated_result.commands.append(post_fix_result)
                        generated_result.postfix_passed = post_fix_result.returncode == 0
                        if not generated_result.postfix_passed:
                            validation = self._generated_test_failure_validation(
                                generated_result,
                                message="Generated regression test failed after the repair patch.",
                            )
                            last_validation = validation
                            self._write_json(
                                artifact_dir / f"attempt-{attempt}-generated-test-validation.json",
                                validation.model_dump(mode="json"),
                            )
                            feedback = validation.failure_summary or ["Generated regression test failed after repair."]
                            last_failure = "; ".join(feedback)
                            continue
                        if target_config is None or target_config.generated_tests.commit_when_stable:
                            generated_result.committed = True
                            applied_patch = self._combine_patches(applied_patch, generated_patch)

                    self._write_text(artifact_dir / f"attempt-{attempt}.patch", applied_patch.diff_text)
                    validation = self.validator.validate(
                        workspace,
                        applied_patch.changed_files,
                        attempt_context,
                        self.config.validation,
                        target_config=target_config,
                        incident=incident,
                    )
                    validation.generated_test = generated_result
                    if generated_result is not None and generated_result.commands:
                        validation.commands = generated_result.commands + validation.commands
                    last_validation = validation
                    self._write_json(
                        artifact_dir / f"attempt-{attempt}-validation.json",
                        validation.model_dump(mode="json"),
                    )
                except PatchGuardrailError as exc:
                    feedback = [str(exc)]
                    last_failure = str(exc)
                    continue
                except Exception as exc:
                    feedback = [str(exc)]
                    last_failure = str(exc)
                    continue

                if not validation.is_success:
                    feedback = validation.failure_summary or ["Validation failed."]
                    last_failure = "; ".join(feedback)
                    continue

                pr_result = None
                if publish:
                    try:
                        pr_result = self.publisher.publish(
                            workspace,
                            incident=incident,
                            analysis=analysis,
                            applied_patch=applied_patch,
                            validation=validation,
                            base_branch=base_branch,
                            commit_title=proposal.commit_message_title,
                        )
                        self._write_json(
                            artifact_dir / f"attempt-{attempt}-pr.json",
                            pr_result.model_dump(mode="json"),
                        )
                    except PublisherError as exc:
                        last_failure = str(exc)

                result = RepairResult(
                    root_cause_summary=analysis.root_cause_summary,
                    changed_files=applied_patch.changed_files,
                    diff_summary=self.patch_engine.summarize_diff(applied_patch.diff_text),
                    syntax_check=validation.syntax_check,
                    tests_run=[item.command for item in validation.commands],
                    pr_url=pr_result.pr_url if pr_result else None,
                    status="pr_created" if pr_result else "validated",
                    analysis=analysis,
                    validation=validation,
                    generated_test=validation.generated_test,
                    artifact_dir=str(artifact_dir),
                    branch=pr_result.branch if pr_result else None,
                    failure_reason=last_failure,
                )
                self._write_result_bundle(artifact_dir, result)
                return result

        result = RepairResult(
            root_cause_summary=analysis.root_cause_summary,
            diff_summary="No validated patch was produced.",
            syntax_check=bool(last_validation and last_validation.syntax_check),
            tests_run=[item.command for item in last_validation.commands] if last_validation else [],
            status="needs_manual_intervention",
            analysis=analysis,
            validation=last_validation,
            generated_test=last_validation.generated_test if last_validation else None,
            artifact_dir=str(artifact_dir),
            failure_reason=last_failure or "Patch generation and validation failed repeatedly.",
        )
        self._write_result_bundle(artifact_dir, result)
        return result

    def _prepare_generated_test(
        self,
        *,
        workspace: Path,
        incident: Incident,
        analysis,
        repo_context,
        target_config: TargetSettings | None,
        artifact_dir: Path,
        attempt: int,
        feedback: list[str],
    ) -> tuple[GeneratedTestResult | None, AppliedPatch | None]:
        if target_config is None or not target_config.generated_tests.enabled:
            return None, None
        result = GeneratedTestResult(attempted=True)
        if self.generated_test_agent is None:
            result.fallback_reason = "Generated test agent is not configured."
            return result, None

        framework = self.framework_detector.detect(workspace, target_config)
        result.framework = framework.framework
        if not framework.is_supported:
            result.fallback_reason = framework.reason or "No supported test framework was detected."
            return result, None

        try:
            proposal = self.generated_test_agent.propose(incident, analysis, repo_context, framework, feedback=feedback)
            self._write_json(
                artifact_dir / f"attempt-{attempt}-generated-test-proposal.json",
                proposal.model_dump(mode="json"),
            )
        except Exception as exc:
            result.fallback_reason = f"Generated test proposal failed: {exc}"
            return result, None

        result.test_path = proposal.test_path
        result.test_name = proposal.test_name
        if not proposal.test_path or not proposal.updated_content:
            result.fallback_reason = proposal.summary or "Generated test proposal did not include a test file."
            return result, None
        proposal.run_command = self.generated_test_runner.build_command(
            workspace,
            proposal,
            framework,
            self.config.validation,
        )
        result.run_command = proposal.run_command

        original_path = (workspace / proposal.test_path).resolve()
        if not original_path.is_relative_to(workspace):
            result.fallback_reason = "Generated test path escapes the repository root."
            return result, None
        original_exists = original_path.exists()
        original_content = original_path.read_text(encoding="utf-8", errors="ignore") if original_exists else None

        try:
            generated_patch = self.patch_engine.apply(
                workspace,
                PatchProposal(
                    summary=proposal.summary or "Generated regression test.",
                    patches=[
                        FilePatch(
                            path=proposal.test_path,
                            reason="Generated regression test for the incident.",
                            updated_content=proposal.updated_content,
                        )
                    ],
                ),
                allowed_paths=[proposal.test_path],
                guardrails=GuardrailSettings(
                    max_changed_files=target_config.generated_tests.max_files,
                    max_patch_lines=self.config.guardrails.max_patch_lines,
                    min_confidence=self.config.guardrails.min_confidence,
                    ignored_paths=self.config.guardrails.ignored_paths,
                ),
            )
        except PatchGuardrailError as exc:
            result.fallback_reason = str(exc)
            return result, None

        if not generated_patch.changed_files:
            result.fallback_reason = "Generated test proposal produced no file changes."
            return result, None

        prefix_result = self.generated_test_runner.run(workspace, proposal, framework, self.config.validation)
        result.commands.append(prefix_result)
        result.prefix_failed = self.generated_test_validator.is_prefix_failure_related(prefix_result, incident)
        if not result.prefix_failed:
            self._restore_generated_test(original_path, original_exists, original_content)
            if target_config.generated_tests.fallback_to_v2_on_failure:
                result.fallback_reason = self._generated_test_fallback_reason(prefix_result)
                return result, None
            return result, None

        self._write_text(artifact_dir / f"attempt-{attempt}-generated-test.patch", generated_patch.diff_text)
        return result, generated_patch

    def _generated_test_requires_failure(
        self,
        result: GeneratedTestResult | None,
        target_config: TargetSettings | None,
    ) -> bool:
        if result is None or target_config is None:
            return False
        if result.fallback_reason is not None:
            return False
        return result.attempted and result.prefix_failed is not True and not target_config.generated_tests.fallback_to_v2_on_failure

    def _generated_test_failure_validation(
        self,
        result: GeneratedTestResult | None,
        message: str = "Generated regression test could not be verified before repair.",
    ) -> ValidationResult:
        commands = result.commands if result is not None else []
        return ValidationResult(
            syntax_check=True,
            tests_passed=False,
            tests_executed=bool(commands),
            commands=commands,
            failure_summary=[message],
            generated_test=result,
        )

    def _restore_generated_test(self, path: Path, existed: bool, content: str | None) -> None:
        if existed:
            path.write_text(content or "", encoding="utf-8")
        elif path.exists():
            path.unlink()

    def _generated_test_fallback_reason(self, command_result) -> str:
        if command_result.returncode == 0:
            return "Generated regression test did not fail before the repair."
        output = f"{command_result.stdout}\n{command_result.stderr}".lower()
        infrastructure_markers = self.generated_test_validator.INFRASTRUCTURE_FAILURE_MARKERS
        if any(marker in output for marker in infrastructure_markers):
            return "Generated regression test failed for infrastructure reasons before repair."
        return "Generated regression test failed before repair, but the failure did not match the incident."

    def _analysis_for_repair_patch(self, analysis, target_config: TargetSettings | None):
        if target_config is None or not target_config.generated_tests.enabled:
            return analysis
        source_targets = [
            target for target in analysis.candidate_targets if not self._is_test_path(target.path)
        ]
        if not source_targets:
            return analysis
        return analysis.model_copy(update={"candidate_targets": source_targets})

    def _is_test_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/").lower()
        parts = normalized.split("/")
        filename = parts[-1] if parts else normalized
        test_dirs = {"test", "tests", "__tests__", "spec", "specs"}
        if any(part in test_dirs for part in parts[:-1]):
            return True
        return (
            filename.startswith("test_")
            or filename.endswith("_test.py")
            or ".test." in filename
            or ".spec." in filename
        )

    def _combine_patches(self, repair_patch: AppliedPatch, generated_patch: AppliedPatch) -> AppliedPatch:
        changed_files = list(dict.fromkeys(repair_patch.changed_files + generated_patch.changed_files))
        return AppliedPatch(
            changed_files=changed_files,
            diff_text="\n".join(part for part in [repair_patch.diff_text, generated_patch.diff_text] if part),
            patch_line_count=repair_patch.patch_line_count + generated_patch.patch_line_count,
            summary="; ".join(part for part in [repair_patch.summary, generated_patch.summary] if part),
            workspace_path=repair_patch.workspace_path,
        )

    def _create_artifact_dir(self, incident) -> Path:
        root = Path(self.config.runtime.artifact_root).resolve()
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        run_name = incident.incident_id or timestamp
        artifact_dir = root / f"{timestamp}-{run_name}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    @contextmanager
    def _temporary_workspace(self, source_repo: Path) -> Path:
        """创建临时工作目录，使用完毕后自动清理"""
        target = Path(tempfile.mkdtemp(prefix="agentfix-"))
        destination = target / source_repo.name
        try:
            shutil.copytree(
                source_repo,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
            )
            yield destination
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(target)
            except Exception:
                pass  # 忽略清理错误

    def _write_result_bundle(self, artifact_dir: Path, result: RepairResult) -> None:
        self._write_json(artifact_dir / "repair-result.json", result.model_dump(mode="json"))
        self._write_text(artifact_dir / "repair-report.md", self._render_markdown_report(result))

    def _render_markdown_report(self, result: RepairResult) -> str:
        validation_lines = "\n".join(f"- `{command}`" for command in result.tests_run) or "- none"
        validation_status = "not available"
        if result.validation is not None:
            if result.validation.tests_executed:
                validation_status = "tests executed"
            elif result.validation.tests_skipped_reason:
                validation_status = f"tests skipped: {result.validation.tests_skipped_reason}"
            else:
                validation_status = "tests skipped"
        generated_test_status = "not attempted"
        if result.generated_test is not None:
            if result.generated_test.is_stable and result.generated_test.committed:
                generated_test_status = f"committed {result.generated_test.test_path}"
            elif result.generated_test.fallback_reason:
                generated_test_status = f"fallback: {result.generated_test.fallback_reason}"
            else:
                generated_test_status = "attempted but not accepted"
        return (
            "# AgentFix Repair Report\n\n"
            f"- Status: `{result.status}`\n"
            f"- Root cause: {result.root_cause_summary}\n"
            f"- Changed files: {', '.join(result.changed_files) if result.changed_files else 'none'}\n"
            f"- PR URL: {result.pr_url or 'not created'}\n"
            f"- Failure reason: {result.failure_reason or 'none'}\n\n"
            "## Validation Status\n"
            f"- Syntax check: `{'passed' if result.syntax_check else 'failed'}`\n"
            f"- Functional tests: {validation_status}\n\n"
            "## Generated Regression Test\n"
            f"- {generated_test_status}\n\n"
            "## Validation Commands\n"
            f"{validation_lines}\n\n"
            "## Diff Summary\n"
            f"```diff\n{result.diff_summary}\n```\n"
        )

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_text(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
