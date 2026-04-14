from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable

from agentfix.config import GuardrailSettings
from agentfix.models import CandidateFile, Incident, RepoContext, RepoMetadata, StackFrame


DEPENDENCY_FILE_NAMES = {
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.cfg",
    "setup.py",
}


class RepoContextCollector:
    def __init__(self, guardrails: GuardrailSettings) -> None:
        self.guardrails = guardrails

    def collect(self, repo_path: str | Path, incident: Incident, base_branch: str = "main") -> RepoContext:
        root = Path(repo_path).resolve()
        python_files = [
            path
            for path in root.rglob("*.py")
            if path.is_file() and not self._is_ignored(root, path)
        ]
        recent_files = self._recent_files(root)
        candidates = self._rank_candidates(root, python_files, incident, recent_files)
        metadata = RepoMetadata(
            repo_path=str(root),
            base_branch=base_branch,
            current_branch=self._git_output(root, ["rev-parse", "--abbrev-ref", "HEAD"]),
            remote_url=self._git_output(root, ["remote", "get-url", "origin"]),
            recent_files=recent_files,
            test_candidates=self._infer_tests(root, candidates),
            dependency_files=[
                str(path.relative_to(root)).replace("\\", "/")
                for path in root.rglob("*")
                if path.is_file() and path.name in DEPENDENCY_FILE_NAMES
            ],
        )
        return RepoContext(
            metadata=metadata,
            candidate_files=candidates,
            ignored_paths=self.guardrails.ignored_paths,
        )

    def _rank_candidates(
        self,
        root: Path,
        python_files: list[Path],
        incident: Incident,
        recent_files: list[str],
    ) -> list[CandidateFile]:
        frames = incident.stack_frames
        exception_tokens = self._exception_tokens(incident.exception_message)
        ranked: list[CandidateFile] = []
        for path in python_files:
            relative_path = str(path.relative_to(root)).replace("\\", "/")
            content = path.read_text(encoding="utf-8", errors="ignore")
            score = 0.0
            reasons: list[str] = []

            for frame in frames:
                frame_path = frame.file_path.replace("\\", "/")
                if frame_path.endswith(relative_path):
                    score += 120
                    reasons.append("exact traceback path match")
                elif Path(frame_path).name == path.name:
                    score += 80
                    reasons.append("traceback filename match")
                if frame.function_name and frame.function_name in content:
                    score += 10
                    reasons.append(f"mentions traceback function {frame.function_name}")
                if frame.code_line and frame.code_line.strip() and frame.code_line.strip() in content:
                    score += 25
                    reasons.append("contains traceback source line")

            if incident.suspected_module and incident.suspected_module in relative_path:
                score += 20
                reasons.append("matches suspected module")

            for token in exception_tokens:
                if token and token in content:
                    score += 8
                    reasons.append(f"contains error token {token}")

            if relative_path in recent_files:
                score += 15
                reasons.append("recently changed in git history")

            if score <= 0:
                continue

            excerpt = self._build_excerpt(root, path, frames)
            ranked.append(
                CandidateFile(
                    relative_path=relative_path,
                    absolute_path=str(path),
                    score=score,
                    reasons=self._unique(reasons),
                    excerpt=excerpt,
                    full_content=content,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:8]

    def _build_excerpt(self, root: Path, path: Path, frames: list[StackFrame]) -> str:
        content_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        relevant_lines = [
            frame.line_number
            for frame in frames
            if Path(frame.file_path).name == path.name
            or frame.file_path.replace("\\", "/").endswith(str(path.relative_to(root)).replace("\\", "/"))
        ]
        if not relevant_lines:
            return "\n".join(content_lines[:80])
        chosen = relevant_lines[0]
        start = max(chosen - 6, 1)
        end = min(chosen + 6, len(content_lines))
        excerpt_lines = [
            f"{index}: {content_lines[index - 1]}"
            for index in range(start, end + 1)
        ]
        return "\n".join(excerpt_lines)

    def _infer_tests(self, root: Path, candidates: Iterable[CandidateFile]) -> list[str]:
        discovered: list[str] = []
        tests_root = root / "tests"
        if not tests_root.exists():
            return discovered
        for candidate in candidates:
            candidate_path = Path(candidate.relative_path)
            stem = candidate_path.stem
            mirrors = [
                tests_root / f"test_{stem}.py",
                tests_root / candidate_path.parent / f"test_{stem}.py",
                tests_root / f"{stem}_test.py",
            ]
            for mirror in mirrors:
                if mirror.exists():
                    discovered.append(str(mirror.relative_to(root)).replace("\\", "/"))
        return self._unique(discovered)

    def _exception_tokens(self, message: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]+", message)
        return self._unique(tokens)

    def _recent_files(self, root: Path) -> list[str]:
        output = self._git_output(root, ["log", "--name-only", "--pretty=format:", "-n", "20"])
        if not output:
            return []
        recent = [line.strip() for line in output.splitlines() if line.strip()]
        return self._unique(recent)

    def _git_output(self, root: Path, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _is_ignored(self, root: Path, path: Path) -> bool:
        relative = str(path.relative_to(root)).replace("\\", "/")
        return any(token in relative.split("/") for token in self.guardrails.ignored_paths)

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
