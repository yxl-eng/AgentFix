from __future__ import annotations

from textwrap import dedent

from agentfix.config import AppConfig
from agentfix.models import AnalysisResult, Incident, PatchProposal, RepoContext
from agentfix.providers.base import StructuredModelProvider


PATCH_INSTRUCTIONS = dedent(
    """
    你是 AgentFix 的补丁生成专家，负责为多语言 Web 服务生成最小安全修复。
    只返回结构化结果，并遵守这些规则：
    - 最多只编辑明确允许的文件。
    - 尽量保留无关代码和原有格式。
    - 不删除测试、不修改依赖、不引入大范围重构。
    - 对每个改动文件返回完整的更新后文件内容。
    - 补丁必须聚焦于修复本次 incident。
    - 所有面向人类阅读的文本字段必须使用简体中文，包括：
      summary、patches[].reason、validation_notes、commit_message_title。
    - 文件路径、函数名、异常类型、命令、代码标识符和代码内容保持原文，不要翻译。
    """
).strip()


class PatchAgent:
    def __init__(self, provider: StructuredModelProvider, config: AppConfig) -> None:
        self.provider = provider
        self.config = config

    def propose(
        self,
        incident: Incident,
        analysis: AnalysisResult,
        repo_context: RepoContext,
        feedback: list[str] | None = None,
    ) -> PatchProposal:
        prompt = self._build_prompt(incident, analysis, repo_context, feedback or [])
        return self.provider.generate_structured(
            instructions=PATCH_INSTRUCTIONS,
            prompt=prompt,
            output_model=PatchProposal,
            reasoning_effort=self.config.openai.patch_reasoning_effort,
        )

    def _build_prompt(
        self,
        incident: Incident,
        analysis: AnalysisResult,
        repo_context: RepoContext,
        feedback: list[str],
    ) -> str:
        allowed_paths = [target.path for target in analysis.candidate_targets[: self.config.guardrails.max_changed_files]]
        file_context_blocks: list[str] = []
        for candidate in repo_context.candidate_files:
            if candidate.relative_path not in allowed_paths:
                continue
            file_context_blocks.append(
                "\n".join(
                    [
                        f"FILE: {candidate.relative_path}",
                        "```text",
                        candidate.full_content,
                        "```",
                    ]
                )
            )

        feedback_block = "\n".join(f"- {item}" for item in feedback) if feedback else "- none"
        plan_block = "\n".join(f"- {step}" for step in analysis.repair_plan) if analysis.repair_plan else "- none"
        target_block = "\n".join(
            f"- {target.path}: {target.change_summary} (confidence={target.confidence:.2f})"
            for target in analysis.candidate_targets
        ) or "- none"

        return dedent(
            f"""
            INCIDENT
            exception_type: {incident.exception_type}
            exception_message: {incident.exception_message}
            trigger_hint: {incident.trigger_hint or "unknown"}
            raw_log:
            ```text
            {incident.log_text[:6000]}
            ```

            ANALYSIS
            root_cause_summary: {analysis.root_cause_summary}
            confidence: {analysis.confidence}
            candidate_targets:
            {target_block}
            repair_plan:
            {plan_block}

            ALLOWED FILES
            {", ".join(allowed_paths) if allowed_paths else "(none)"}

            PREVIOUS VALIDATION FEEDBACK
            {feedback_block}

            FILE CONTENTS
            {chr(10).join(file_context_blocks) if file_context_blocks else "(no file content available)"}

            TASK
            生成一个能修复本次 incident 的最小补丁方案。
            如果置信度太低，请返回空 patches，并在 summary 中用中文说明为什么不能自动修改。
            """
        ).strip()
