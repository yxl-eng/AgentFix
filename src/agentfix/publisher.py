from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agentfix.config import GitHubSettings
from agentfix.models import AnalysisResult, AppliedPatch, Incident, PullRequestResult, ValidationResult


class PublisherError(RuntimeError):
    pass


class GitHubPublisher:
    def __init__(self, settings: GitHubSettings) -> None:
        self.settings = settings

    def publish(
        self,
        repo_path: str | Path,
        *,
        incident: Incident,
        analysis: AnalysisResult,
        applied_patch: AppliedPatch,
        validation: ValidationResult,
        base_branch: str,
        commit_title: str | None = None,
    ) -> PullRequestResult:
        root = Path(repo_path).resolve()
        branch = self.build_branch_name(incident)
        title = self.build_pr_title(incident, analysis)
        body = self.build_pr_body(incident, analysis, applied_patch, validation)
        commit_message = commit_title or self.build_commit_message(incident)

        try:
            self._git(root, ["checkout", base_branch])
        except PublisherError:
            pass
        self._git(root, ["checkout", "-B", branch])
        self._git(root, ["add", "--", *applied_patch.changed_files])
        self._git(root, ["commit", "-m", commit_message])
        sha = self._git(root, ["rev-parse", "HEAD"]).stdout.strip()
        self._git(root, ["push", "-u", "origin", branch])
        pr_url = self._create_pull_request(root, branch=branch, base_branch=base_branch, title=title, body=body)
        return PullRequestResult(
            branch=branch,
            commit_sha=sha,
            pr_url=pr_url,
            title=title,
            body=body,
        )

    def create_pr_for_existing_branch(
        self,
        repo_path: str | Path,
        *,
        branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> PullRequestResult:
        root = Path(repo_path).resolve()
        sha = self._git(root, ["rev-parse", "HEAD"]).stdout.strip()
        pr_url = self._create_pull_request(root, branch=branch, base_branch=base_branch, title=title, body=body)
        return PullRequestResult(branch=branch, commit_sha=sha, pr_url=pr_url, title=title, body=body)

    def build_branch_name(self, incident: Incident) -> str:
        raw_id = incident.incident_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        short_exception = self._slugify(incident.exception_type or "unknown-error")
        return f"agentfix/{self._slugify(raw_id)}/{short_exception}"

    def build_commit_message(self, incident: Incident) -> str:
        incident_id = incident.incident_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"fix: auto-repair {incident.exception_type} from incident {incident_id}"

    def build_pr_title(self, incident: Incident, analysis: AnalysisResult) -> str:
        return f"[agentfix] {incident.exception_type}: {analysis.root_cause_summary[:72]}"

    def build_pr_body(
        self,
        incident: Incident,
        analysis: AnalysisResult,
        applied_patch: AppliedPatch,
        validation: ValidationResult,
    ) -> str:
        changed = "\n".join(f"- `{path}`" for path in applied_patch.changed_files) or "- none"
        validation_lines = "\n".join(
            f"- `{result.command}` -> {result.returncode}"
            for result in validation.commands
        ) or "- no validation commands executed"
        risks = "\n".join(f"- {note}" for note in analysis.additional_notes) or "- Human review recommended before merge."
        return (
            "## Error Summary\n"
            f"- Service: `{incident.service_name}`\n"
            f"- Environment: `{incident.environment}`\n"
            f"- Exception: `{incident.exception_type}: {incident.exception_message}`\n\n"
            "## Root Cause\n"
            f"{analysis.root_cause_summary}\n\n"
            "## Code Changes\n"
            f"{changed}\n\n"
            "## Validation\n"
            f"{validation_lines}\n\n"
            "## Risk / Human Review\n"
            f"{risks}\n"
        )

    def _create_pull_request(
        self,
        repo_path: Path,
        *,
        branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        remote_url = self._git(repo_path, ["remote", "get-url", "origin"]).stdout.strip()
        owner, repo = self._parse_github_remote(remote_url)
        token = self.settings.resolved_token()
        if not token:
            raise PublisherError(
                f"GitHub token missing. Set {self.settings.token_env_var} before creating a PR."
            )

        payload = json.dumps(
            {
                "title": title,
                "head": branch,
                "base": base_branch,
                "body": body,
                "draft": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.settings.api_base_url}/repos/{owner}/{repo}/pulls",
            data=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover
            details = exc.read().decode("utf-8", errors="ignore")
            raise PublisherError(f"GitHub PR creation failed: {details}") from exc
        return data["html_url"]

    def _parse_github_remote(self, remote_url: str) -> tuple[str, str]:
        match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", remote_url)
        if not match:
            raise PublisherError(f"Unsupported GitHub remote URL: {remote_url}")
        return match.group("owner"), match.group("repo")

    def _git(self, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise PublisherError(
                f"git {' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed

    def _slugify(self, value: str) -> str:
        lowered = value.lower().strip()
        lowered = re.sub(r"[^a-z0-9._/-]+", "-", lowered)
        lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
        return lowered or "unknown"
