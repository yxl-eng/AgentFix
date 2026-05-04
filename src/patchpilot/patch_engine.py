from __future__ import annotations

from difflib import unified_diff
from pathlib import Path

from patchpilot.config import GuardrailSettings
from patchpilot.models import AppliedPatch, PatchProposal


BLOCKED_FILENAMES = {
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.cfg",
    "setup.py",
}


class PatchGuardrailError(RuntimeError):
    pass


class PatchEngine:
    def apply(
        self,
        repo_path: str | Path,
        proposal: PatchProposal,
        allowed_paths: list[str],
        guardrails: GuardrailSettings,
    ) -> AppliedPatch:
        root = Path(repo_path).resolve()
        normalized_allowed = {self._normalize(path) for path in allowed_paths}
        if not normalized_allowed and proposal.patches:
            raise PatchGuardrailError("没有可编辑的已批准文件。")
        if len(proposal.patches) > guardrails.max_changed_files:
            raise PatchGuardrailError("补丁方案超过最大修改文件数限制。")

        changed_files: list[str] = []
        diff_chunks: list[str] = []
        patch_line_count = 0

        for file_patch in proposal.patches:
            relative_path = self._normalize(file_patch.path)
            target_path = (root / relative_path).resolve()
            if normalized_allowed and relative_path not in normalized_allowed:
                raise PatchGuardrailError(f"补丁试图修改未批准文件：{relative_path}")
            if not target_path.is_relative_to(root):
                raise PatchGuardrailError(f"补丁路径越出了仓库目录：{relative_path}")
            if target_path.name in BLOCKED_FILENAMES:
                raise PatchGuardrailError(f"补丁试图修改被禁止的依赖文件：{relative_path}")

            original = ""
            if target_path.exists():
                original = target_path.read_text(encoding="utf-8", errors="ignore")

            diff = "".join(
                unified_diff(
                    original.splitlines(keepends=True),
                    file_patch.updated_content.splitlines(keepends=True),
                    fromfile=relative_path,
                    tofile=relative_path,
                )
            )
            if not diff:
                continue

            patch_line_count += self._count_changed_lines(diff)
            if patch_line_count > guardrails.max_patch_lines:
                raise PatchGuardrailError("补丁方案超过最大修改行数限制。")

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(file_patch.updated_content, encoding="utf-8")
            changed_files.append(relative_path)
            diff_chunks.append(diff)

        return AppliedPatch(
            changed_files=changed_files,
            diff_text="\n".join(diff_chunks),
            patch_line_count=patch_line_count,
            summary=proposal.summary,
            workspace_path=str(root),
        )

    def summarize_diff(self, diff_text: str, max_lines: int = 40) -> str:
        lines = diff_text.splitlines()
        if len(lines) <= max_lines:
            return diff_text
        return "\n".join(lines[:max_lines] + ["..."])

    def _count_changed_lines(self, diff_text: str) -> int:
        count = 0
        for line in diff_text.splitlines():
            if line.startswith(("+++", "---", "@@")):
                continue
            if line.startswith("+") or line.startswith("-"):
                count += 1
        return count

    def _normalize(self, path: str) -> str:
        return str(Path(path)).replace("\\", "/")
