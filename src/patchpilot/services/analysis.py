from __future__ import annotations

from textwrap import dedent

from patchpilot.config import AppConfig
from patchpilot.models import AnalysisResult, Incident, RepoContext
from patchpilot.providers.base import StructuredModelProvider


ANALYSIS_INSTRUCTIONS = dedent(
    """
    你是 PatchPilot 的线上事故根因分析专家，负责分析多语言 Web 服务的生产报错。
    只返回结构化结果，并遵守这些规则：
    - 根据日志、Traceback 和代码上下文判断最可能的根因。
    - 只选择仓库上下文中真实存在的文件。
    - 优先选择最小、安全、可验证的代码修改。
    - 避免修改依赖、重写架构或做猜测性大改。
    - confidence 必须是 0 到 1 之间的浮点数。
    - 如果上下文不足、语言/运行时不清晰，或多个根因都可能成立，需要降低 confidence。
    - 所有面向人类阅读的文本字段必须使用简体中文，包括：
      root_cause_summary、candidate_targets[].rationale、candidate_targets[].change_summary、
      repair_plan、validation_focus、additional_notes。
    - 文件路径、函数名、异常类型、命令、代码标识符和日志原文保持原文，不要翻译。
    """
).strip()


class AnalysisAgent:
    def __init__(self, provider: StructuredModelProvider, config: AppConfig) -> None:
        self.provider = provider
        self.config = config

    def analyze(self, incident: Incident, repo_context: RepoContext) -> AnalysisResult:
        prompt = self._build_prompt(incident, repo_context)
        return self.provider.generate_structured(
            instructions=ANALYSIS_INSTRUCTIONS,
            prompt=prompt,
            output_model=AnalysisResult,
            reasoning_effort=self.config.openai.analysis_reasoning_effort,
        )

    def _build_prompt(self, incident: Incident, repo_context: RepoContext) -> str:
        candidate_blocks: list[str] = []
        for candidate in repo_context.candidate_files[:5]:
            candidate_blocks.append(
                "\n".join(
                    [
                        f"FILE: {candidate.relative_path}",
                        f"SCORE: {candidate.score}",
                        f"REASONS: {', '.join(candidate.reasons)}",
                        "EXCERPT:",
                        "```text",
                        candidate.excerpt or candidate.full_content[:4000],
                        "```",
                    ]
                )
            )

        traceback_block = "\n".join(
            [
                f'{frame.file_path}:{frame.line_number} in {frame.function_name}'
                + (f" -> {frame.code_line}" if frame.code_line else "")
                for frame in incident.stack_frames
            ]
        ) or "(no traceback frames parsed)"

        return dedent(
            f"""
            INCIDENT
            service_name: {incident.service_name}
            environment: {incident.environment}
            incident_id: {incident.incident_id or "unknown"}
            exception_type: {incident.exception_type}
            exception_message: {incident.exception_message}
            suspected_module: {incident.suspected_module or "unknown"}
            trigger_hint: {incident.trigger_hint or "unknown"}

            TRACEBACK
            {traceback_block}

            RAW LOG
            ```text
            {incident.log_text[:6000]}
            ```

            CANDIDATE FILES
            {chr(10).join(candidate_blocks) if candidate_blocks else "(no candidate files found)"}

            TASK
            1. 判断最可能的根因，并用中文写入 root_cause_summary。
            2. 最多选择三个应该修改的文件。
            3. 用中文描述最小修复计划。
            4. 用中文说明语法检查、自动生成回归测试、已有测试和服务验证的关注点。
            """
        ).strip()
