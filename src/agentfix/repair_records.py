from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentfix.config import RecordsSettings
from agentfix.models import RepairRecord


class RepairRecordWriter:
    def __init__(self, settings: RecordsSettings, project_root: str | Path | None = None) -> None:
        self.settings = settings
        self.project_root = Path(project_root or ".").resolve()

    def write(self, record: RepairRecord, *, commit: bool | None = None) -> RepairRecord:
        records_root = (self.project_root / self.settings.root).resolve()
        records_root.mkdir(parents=True, exist_ok=True)
        safe_id = self._safe_name(record.incident_id)
        json_path = records_root / f"{safe_id}.json"
        markdown_path = records_root / f"{safe_id}.md"
        record.record_json_path = str(json_path)
        record.record_markdown_path = str(markdown_path)
        json_path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        markdown_path.write_text(self._render_markdown(record), encoding="utf-8")
        should_commit = self.settings.auto_commit if commit is None else commit
        if should_commit:
            self._commit_records([json_path, markdown_path], record)
        return record

    def _render_markdown(self, record: RepairRecord) -> str:
        result = record.repair_result
        changed_files = ", ".join(result.changed_files) if result and result.changed_files else "none"
        validation = "not available"
        if result and result.validation:
            validation = "passed" if result.validation.is_success else "failed"
        generated_test = "not attempted"
        if result and result.generated_test:
            if result.generated_test.is_stable and result.generated_test.committed:
                generated_test = f"committed {result.generated_test.test_path}"
            elif result.generated_test.fallback_reason:
                generated_test = f"fallback: {result.generated_test.fallback_reason}"
            else:
                generated_test = "attempted but not accepted"
        tool_lines = "\n".join(
            f"- `{tool.name}`: {tool.status} - {tool.summary}"
            for tool in record.tool_calls
        ) or "- none"
        return (
            "# AgentFix Repair Record\n\n"
            f"- Incident: `{record.incident_id}`\n"
            f"- Target: `{record.target}`\n"
            f"- Source: `{record.source}`\n"
            f"- Status: `{record.status}`\n"
            f"- Message: {record.message}\n"
            f"- PR URL: {record.pr_url or 'not created'}\n"
            f"- Changed files: {changed_files}\n"
            f"- Validation: {validation}\n\n"
            f"- Generated test: {generated_test}\n\n"
            "## Tool Calls\n"
            f"{tool_lines}\n"
        )

    def _commit_records(self, paths: list[Path], record: RepairRecord) -> None:
        relative_paths = [str(path.relative_to(self.project_root)) for path in paths]
        add_result = self._git(["add", "--", *relative_paths])
        if add_result.returncode != 0:
            return
        self._git(["commit", "-m", f"docs: record agentfix repair {record.incident_id}"])

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return subprocess.CompletedProcess(args=["git", *args], returncode=1, stderr=str(exc))

    def _safe_name(self, value: str) -> str:
        return "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-") or "incident"
