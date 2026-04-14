from __future__ import annotations

from textwrap import dedent

from agentfix.config import AppConfig
from agentfix.models import AnalysisResult, Incident, RepoContext
from agentfix.providers.base import StructuredModelProvider


ANALYSIS_INSTRUCTIONS = dedent(
    """
    You analyze Python production incidents for an automated repair pipeline.
    Return only structured output that:
    - identifies the most likely root cause using the supplied traceback and code context
    - ranks only files that are present in the repository context
    - prefers the smallest safe code change
    - avoids dependency changes, rewrites, and speculative architecture edits
    - expresses every confidence value as a float between 0 and 1
    - lowers confidence if the context is weak or multiple root causes are equally plausible
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
                        "```python",
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

            CANDIDATE FILES
            {chr(10).join(candidate_blocks) if candidate_blocks else "(no candidate files found)"}

            TASK
            1. Determine the most likely root cause.
            2. Choose at most three files that should be edited.
            3. Describe a minimal fix plan.
            4. Provide validation focus areas for syntax checks and tests.
            """
        ).strip()
