from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover - fallback for minimal local doctor/validation environments
    def retry(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

from patchpilot.config import GitHubSettings
from patchpilot.models import AnalysisResult, AppliedPatch, Incident, PullRequestResult, ValidationResult


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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"patchpilot/{self._slugify(raw_id)}/{short_exception}-{timestamp}"

    def build_commit_message(self, incident: Incident) -> str:
        incident_id = incident.incident_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"fix: 修复 incident {incident_id} 中的 {incident.exception_type}"

    def build_pr_title(self, incident: Incident, analysis: AnalysisResult) -> str:
        return f"[PatchPilot] 自动修复 {incident.exception_type}: {analysis.root_cause_summary[:72]}"

    def build_pr_body(
        self,
        incident: Incident,
        analysis: AnalysisResult,
        applied_patch: AppliedPatch,
        validation: ValidationResult,
    ) -> str:
        changed = "\n".join(f"- `{path}`" for path in applied_patch.changed_files) or "- 无"
        validation_lines = "\n".join(
            f"- `{result.command}` -> {result.returncode}"
            for result in validation.commands
        ) or "- 未执行验证命令"
        generated_test = validation.generated_test
        if generated_test is None:
            generated_test_block = "- 未尝试生成回归测试"
        elif generated_test.is_stable and generated_test.committed:
            generated_test_block = f"- 已提交 `{generated_test.test_path}` ({generated_test.framework})"
        elif generated_test.fallback_reason:
            generated_test_block = f"- 未采纳，继续既有验证：{generated_test.fallback_reason}"
        else:
            generated_test_block = "- 已尝试生成，但未达到提交条件"
        generated_test_details = self._generated_test_details(generated_test)
        repair_plan = "\n".join(f"- {step}" for step in analysis.repair_plan) or "- 根据根因定位修改相关业务代码，并保持补丁范围尽量小。"
        risks = "\n".join(f"- {note}" for note in analysis.additional_notes) or "- 合并前建议开发者 Review。"
        return (
            "## 错误摘要\n"
            f"- 服务：`{incident.service_name}`\n"
            f"- 环境：`{incident.environment}`\n"
            f"- 异常：`{incident.exception_type}: {incident.exception_message}`\n\n"
            "## 根因分析\n"
            f"{analysis.root_cause_summary}\n\n"
            "## 修改内容\n"
            f"{changed}\n\n"
            "## 修复思路\n"
            f"{repair_plan}\n\n"
            "## 验证结果\n"
            f"{validation_lines}\n\n"
            "## 自动生成回归测试\n"
            f"{generated_test_block}\n"
            f"{generated_test_details}\n\n"
            "## 风险与人工 Review 建议\n"
            f"{risks}\n"
        )

    def _generated_test_details(self, generated_test) -> str:
        if generated_test is None:
            return "- 说明：本次未生成新的回归测试。"
        lines = []
        if generated_test.summary:
            lines.append(f"- 用例介绍：{generated_test.summary}")
        if generated_test.expected_behavior:
            lines.append(f"- 预期行为：{generated_test.expected_behavior}")
        if generated_test.test_cases:
            lines.append("- 覆盖用例：")
            lines.extend(f"  - `{name}`" for name in generated_test.test_cases)
        if not lines:
            lines.append("- 说明：没有额外测试说明。")
        return "\n".join(lines)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
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
                f"缺少 GitHub Token。创建 PR 前请设置 {self.settings.token_env_var}。"
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
            raise PublisherError(f"GitHub PR 创建失败：{details}") from exc
        return data["html_url"]

    def _parse_github_remote(self, remote_url: str) -> tuple[str, str]:
        match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", remote_url)
        if not match:
            raise PublisherError(f"不支持的 GitHub remote URL：{remote_url}")
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
                f"git {' '.join(args)} 执行失败：{completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed

    def _slugify(self, value: str) -> str:
        lowered = value.lower().strip()
        lowered = re.sub(r"[^a-z0-9._/-]+", "-", lowered)
        lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
        return lowered or "unknown"
