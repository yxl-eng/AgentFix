from __future__ import annotations

from textwrap import dedent

from agentfix.config import AppConfig
from agentfix.models import AnalysisResult, Incident, PatchProposal, RepoContext
from agentfix.providers.base import StructuredModelProvider


PATCH_INSTRUCTIONS = dedent(
    """
    You generate minimal safe repair patches for web service code across common languages.
    Return only structured output that:
    - edits at most the explicitly permitted files
    - preserves unrelated code and formatting as much as possible
    - does not delete tests, change dependencies, or introduce broad refactors
    - produces complete updated file contents for each changed file
    - keeps the patch focused on fixing the supplied incident
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
            Generate a minimal patch proposal that fixes the incident.
            If confidence is too low, return an empty patch list and explain why in the summary.
            """
        ).strip()
