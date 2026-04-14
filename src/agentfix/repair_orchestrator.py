from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from agentfix.config import AppConfig
from agentfix.incident_ingest import IncidentIngestor
from agentfix.models import RepairResult, ValidationResult
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
    ) -> None:
        self.config = config
        self.ingestor = ingestor
        self.collector = collector
        self.analyzer = analyzer
        self.patch_agent = patch_agent
        self.patch_engine = patch_engine
        self.validator = validator
        self.publisher = publisher

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
    ) -> ValidationResult:
        incident = self.ingestor.from_file(log_file) if log_file else self.ingestor.placeholder()
        repo_context = self.collector.collect(repo_path, incident, base_branch)
        return self.validator.validate(repo_path, changed_files, repo_context, self.config.validation)

    def run(
        self,
        repo_path: str | Path,
        log_file: str | Path,
        *,
        base_branch: str = "main",
        publish: bool = True,
    ) -> RepairResult:
        source_repo = Path(repo_path).resolve()
        incident = self.ingestor.from_file(log_file)
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
            workspace = self._copy_repo(source_repo)
            attempt_context = self.collector.collect(workspace, incident, base_branch)
            try:
                proposal = self.patch_agent.propose(incident, analysis, attempt_context, feedback=feedback)
                self._write_json(
                    artifact_dir / f"attempt-{attempt}-proposal.json",
                    proposal.model_dump(mode="json"),
                )
                allowed_paths = [
                    target.path
                    for target in analysis.candidate_targets[: self.config.guardrails.max_changed_files]
                ]
                applied_patch = self.patch_engine.apply(
                    workspace,
                    proposal,
                    allowed_paths=allowed_paths,
                    guardrails=self.config.guardrails,
                )
                if not applied_patch.changed_files:
                    raise PatchGuardrailError("Patch proposal produced no file changes.")
                self._write_text(artifact_dir / f"attempt-{attempt}.patch", applied_patch.diff_text)
                validation = self.validator.validate(
                    workspace,
                    applied_patch.changed_files,
                    attempt_context,
                    self.config.validation,
                )
                last_validation = validation
                self._write_json(
                    artifact_dir / f"attempt-{attempt}-validation.json",
                    validation.model_dump(mode="json"),
                )
            except PatchGuardrailError as exc:
                feedback = [str(exc)]
                last_failure = str(exc)
                shutil.rmtree(workspace, ignore_errors=True)
                continue
            except Exception as exc:
                feedback = [str(exc)]
                last_failure = str(exc)
                shutil.rmtree(workspace, ignore_errors=True)
                continue

            if not validation.is_success:
                feedback = validation.failure_summary or ["Validation failed."]
                last_failure = "; ".join(feedback)
                shutil.rmtree(workspace, ignore_errors=True)
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
                artifact_dir=str(artifact_dir),
                branch=pr_result.branch if pr_result else None,
                failure_reason=last_failure,
            )
            self._write_result_bundle(artifact_dir, result)
            shutil.rmtree(workspace, ignore_errors=True)
            return result

        result = RepairResult(
            root_cause_summary=analysis.root_cause_summary,
            diff_summary="No validated patch was produced.",
            syntax_check=bool(last_validation and last_validation.syntax_check),
            tests_run=[item.command for item in last_validation.commands] if last_validation else [],
            status="needs_manual_intervention",
            analysis=analysis,
            validation=last_validation,
            artifact_dir=str(artifact_dir),
            failure_reason=last_failure or "Patch generation and validation failed repeatedly.",
        )
        self._write_result_bundle(artifact_dir, result)
        return result

    def _create_artifact_dir(self, incident) -> Path:
        root = Path(self.config.runtime.artifact_root).resolve()
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        run_name = incident.incident_id or timestamp
        artifact_dir = root / f"{timestamp}-{run_name}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir

    def _copy_repo(self, source_repo: Path) -> Path:
        target = Path(tempfile.mkdtemp(prefix="agentfix-"))
        destination = target / source_repo.name
        shutil.copytree(
            source_repo,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
        )
        return destination

    def _write_result_bundle(self, artifact_dir: Path, result: RepairResult) -> None:
        self._write_json(artifact_dir / "repair-result.json", result.model_dump(mode="json"))
        self._write_text(artifact_dir / "repair-report.md", self._render_markdown_report(result))

    def _render_markdown_report(self, result: RepairResult) -> str:
        validation_lines = "\n".join(f"- `{command}`" for command in result.tests_run) or "- none"
        return (
            "# AgentFix Repair Report\n\n"
            f"- Status: `{result.status}`\n"
            f"- Root cause: {result.root_cause_summary}\n"
            f"- Changed files: {', '.join(result.changed_files) if result.changed_files else 'none'}\n"
            f"- PR URL: {result.pr_url or 'not created'}\n"
            f"- Failure reason: {result.failure_reason or 'none'}\n\n"
            "## Validation Commands\n"
            f"{validation_lines}\n\n"
            "## Diff Summary\n"
            f"```diff\n{result.diff_summary}\n```\n"
        )

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_text(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
