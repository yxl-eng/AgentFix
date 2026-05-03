from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agentfix.config import RecordsSettings
from agentfix.localization import bool_label, disposition_label, risk_label, root_cause_label, status_label
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
        changed_files = ", ".join(result.changed_files) if result and result.changed_files else "无"
        validation = "不可用"
        if result and result.validation:
            validation = "通过" if result.validation.is_success else "失败"
        generated_test = "未尝试"
        if result and result.generated_test:
            if result.generated_test.is_stable and result.generated_test.committed:
                generated_test = f"已提交 {result.generated_test.test_path}"
            elif result.generated_test.fallback_reason:
                generated_test = f"未采纳，继续既有验证：{result.generated_test.fallback_reason}"
            else:
                generated_test = "已尝试但未采纳"
        tool_lines = "\n".join(
            f"- `{tool.name}`: {tool.status} - {tool.summary}"
            for tool in record.tool_calls
        ) or "- 无"
        evidence = record.evidence or (result.evidence if result else [])
        evidence_lines = "\n".join(f"- {item}" for item in evidence) or "- 无"
        tool_plan = record.tool_plan or (result.tool_plan if result else [])
        tool_plan_lines = "\n".join(f"- `{item}`" for item in tool_plan) or "- 无"
        human_steps = record.human_resolution_steps or (result.human_resolution_steps if result else [])
        human_step_lines = "\n".join(f"- {item}" for item in human_steps) or "- 无"
        repair_approach = self._render_repair_approach(result)
        generated_test_details = self._render_generated_test_details(result)
        summary = self._summary_with_decision(record, result)
        return (
            "# AgentFix 处理记录\n\n"
            f"- Incident：`{record.incident_id}`\n"
            f"- Target：`{record.target}`\n"
            f"- 来源：`{record.source}`\n"
            f"- 状态：{status_label(record.status)}（`{record.status}`）\n"
            f"- 处理结论：{disposition_label(record.disposition or (result.disposition if result else None))}\n"
            f"- 根因类型：{root_cause_label(record.root_cause_type or (result.root_cause_type if result else None))}\n"
            f"- 风险等级：{risk_label(record.risk_level or (result.risk_level if result else None))}\n"
            f"- 摘要：{summary}\n"
            f"- 是否需要人工处理：{bool_label(record.human_action_required or (result.human_action_required if result else False))}\n"
            f"- PR URL：{record.pr_url or '未创建'}\n"
            f"- 修改文件：{changed_files}\n"
            f"- 验证结果：{validation}\n"
            f"- 自动生成测试：{generated_test}\n\n"
            "## 修复思路\n"
            f"{repair_approach}\n\n"
            "## 自动生成测试说明\n"
            f"{generated_test_details}\n\n"
            "## 证据\n"
            f"{evidence_lines}\n\n"
            "## 计划调用的工具\n"
            f"{tool_plan_lines}\n\n"
            "## 人工处理建议\n"
            f"{human_step_lines}\n\n"
            "## 工具调用记录\n"
            f"{tool_lines}\n"
        )

    def _summary_with_decision(self, record: RepairRecord, result) -> str:
        summary = record.message or (result.root_cause_summary if result else "") or "无"
        decision = record.decision_reason or (result.decision_reason if result else "")
        if decision and decision not in summary:
            return f"{summary}（处理判断：{decision}）"
        return summary

    def _render_repair_approach(self, result) -> str:
        if result and result.analysis and result.analysis.repair_plan:
            return "\n".join(f"- {item}" for item in result.analysis.repair_plan)
        if result and result.changed_files:
            return "\n".join(
                [
                    "- 根据根因定位修改相关业务代码，保持补丁范围尽量小。",
                    f"- 本次修改文件：{', '.join(result.changed_files)}。",
                    "- 通过语法检查、测试命令和服务验证确认行为是否恢复。",
                ]
            )
        if result and result.failure_reason:
            return f"- 本次没有产生可提交补丁，原因：{result.failure_reason}"
        return "- 无"

    def _render_generated_test_details(self, result) -> str:
        generated_test = result.generated_test if result else None
        if generated_test is None or not generated_test.attempted:
            return "- 说明：本次没有尝试自动生成回归测试。"
        lines = [
            f"- 测试文件：`{generated_test.test_path or '未生成'}`",
            f"- 测试框架：`{generated_test.framework or 'unknown'}`",
        ]
        if generated_test.summary:
            lines.append(f"- 用例介绍：{generated_test.summary}")
        if generated_test.expected_behavior:
            lines.append(f"- 预期行为：{generated_test.expected_behavior}")
        if generated_test.test_cases:
            lines.append("- 覆盖用例：")
            lines.extend(f"  - `{name}`" for name in generated_test.test_cases)
        if generated_test.prefix_failed is not None:
            lines.append(f"- 修复前复现：{'是' if generated_test.prefix_failed else '否'}")
        if generated_test.postfix_passed is not None:
            lines.append(f"- 修复后通过：{'是' if generated_test.postfix_passed else '否'}")
        if generated_test.fallback_reason:
            lines.append(f"- 未采纳原因：{generated_test.fallback_reason}")
        return "\n".join(lines)

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
