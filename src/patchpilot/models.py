from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class StackFrame(BaseModel):
    file_path: str
    line_number: int
    function_name: str
    code_line: str | None = None
    raw_frame: str | None = None


class RequestContext(BaseModel):
    method: str | None = None
    url: str | None = None
    path: str | None = None
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None


class ExpectedOutcome(BaseModel):
    expected_status: int | None = None
    body_contains: str | None = None
    body_not_contains: str | None = None


class Incident(BaseModel):
    service_name: str
    environment: str
    log_text: str
    exception_type: str
    exception_message: str = ""
    stack_frames: list[StackFrame] = Field(default_factory=list)
    suspected_module: str | None = None
    trigger_hint: str | None = None
    incident_id: str | None = None
    occurred_at: str | None = None
    request_context: RequestContext | None = None
    expected_outcome: ExpectedOutcome | None = None


class CandidateFile(BaseModel):
    relative_path: str
    absolute_path: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    excerpt: str = ""
    full_content: str = ""

    @property
    def path(self) -> Path:
        return Path(self.absolute_path)


class RepoMetadata(BaseModel):
    repo_path: str
    base_branch: str
    current_branch: str | None = None
    remote_url: str | None = None
    recent_files: list[str] = Field(default_factory=list)
    test_candidates: list[str] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)


class RepoContext(BaseModel):
    metadata: RepoMetadata
    candidate_files: list[CandidateFile] = Field(default_factory=list)
    ignored_paths: list[str] = Field(default_factory=list)


class RepairIntent(BaseModel):
    path: str
    rationale: str
    confidence: float = Field(ge=0, le=1)
    change_summary: str


class AnalysisResult(BaseModel):
    root_cause_summary: str
    confidence: float = Field(ge=0, le=1)
    candidate_targets: list[RepairIntent] = Field(default_factory=list)
    repair_plan: list[str] = Field(default_factory=list)
    validation_focus: list[str] = Field(default_factory=list)
    additional_notes: list[str] = Field(default_factory=list)


class FilePatch(BaseModel):
    path: str
    reason: str
    updated_content: str


class PatchProposal(BaseModel):
    summary: str
    patches: list[FilePatch] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    commit_message_title: str | None = None


class AppliedPatch(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    diff_text: str = ""
    patch_line_count: int = 0
    summary: str = ""
    workspace_path: str = ""


class ValidationCommandResult(BaseModel):
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""


class TestFrameworkInfo(BaseModel):
    language: str = "unknown"
    framework: str = "unknown"
    reason: str = ""

    @property
    def is_supported(self) -> bool:
        return self.framework != "unknown"


class GeneratedTestProposal(BaseModel):
    summary: str = ""
    framework: str | None = None
    test_path: str | None = None
    test_name: str | None = None
    updated_content: str | None = None
    run_command: str | list[str] | None = None
    expected_behavior: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


class GeneratedTestResult(BaseModel):
    attempted: bool = False
    framework: str | None = None
    test_path: str | None = None
    test_name: str | None = None
    run_command: str | list[str] | None = None
    prefix_failed: bool | None = None
    postfix_passed: bool | None = None
    committed: bool = False
    fallback_reason: str | None = None
    summary: str = ""
    expected_behavior: str = ""
    test_cases: list[str] = Field(default_factory=list)
    commands: list[ValidationCommandResult] = Field(default_factory=list)
    original_test_existed: bool | None = Field(default=None, exclude=True)
    original_test_content: str | None = Field(default=None, exclude=True)

    @property
    def is_stable(self) -> bool:
        return self.prefix_failed is True and self.postfix_passed is True


class PlannerDecision(BaseModel):
    disposition: str = "repair_attempt"
    root_cause_type: str = "code"
    risk_level: str = "medium"
    confidence: float = Field(default=0.0, ge=0, le=1)
    summary: str = ""
    decision_reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    tool_plan: list[str] = Field(default_factory=list)
    human_action_required: bool = False
    human_resolution_steps: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    syntax_check: bool
    tests_passed: bool | None = None
    tests_executed: bool = False
    tests_skipped_reason: str | None = None
    commands: list[ValidationCommandResult] = Field(default_factory=list)
    failure_summary: list[str] = Field(default_factory=list)
    suggested_follow_up: list[str] = Field(default_factory=list)
    generated_test: GeneratedTestResult | None = None

    @property
    def is_success(self) -> bool:
        generated_ok = (
            self.generated_test is None
            or not self.generated_test.attempted
            or self.generated_test.is_stable
            or self.generated_test.fallback_reason is not None
        )
        return self.syntax_check and self.tests_passed is not False and generated_ok


class PullRequestResult(BaseModel):
    branch: str
    commit_sha: str
    pr_url: str
    title: str
    body: str


class RepairIterationRecord(BaseModel):
    attempt: int
    hypothesis: str = ""
    code_context: list[str] = Field(default_factory=list)
    generated_test_summary: str = ""
    patch_summary: str = ""
    validation_feedback: list[str] = Field(default_factory=list)
    next_feedback: list[str] = Field(default_factory=list)
    status: str = "running"


class RepairResult(BaseModel):
    root_cause_summary: str
    changed_files: list[str] = Field(default_factory=list)
    diff_summary: str = ""
    syntax_check: bool = False
    tests_run: list[str] = Field(default_factory=list)
    pr_url: str | None = None
    status: str
    analysis: AnalysisResult | None = None
    validation: ValidationResult | None = None
    artifact_dir: str | None = None
    branch: str | None = None
    failure_reason: str | None = None
    record_json_path: str | None = None
    record_markdown_path: str | None = None
    feishu_notified: bool | None = None
    generated_test: GeneratedTestResult | None = None
    disposition: str | None = None
    decision_reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    tool_plan: list[str] = Field(default_factory=list)
    root_cause_type: str | None = None
    risk_level: str | None = None
    human_action_required: bool = False
    human_resolution_steps: list[str] = Field(default_factory=list)
    planner_decision: PlannerDecision | None = None
    repair_iterations: list[RepairIterationRecord] = Field(default_factory=list)


class RepairEvent(BaseModel):
    source: str
    target: str
    log_text: str = ""
    log_file: str | None = None
    incident_id: str | None = None
    base_branch: str | None = None
    delivery_id: str | None = None
    issue_url: str | None = None
    issue_title: str | None = None
    request_context: RequestContext | None = None
    expected_outcome: ExpectedOutcome | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(BaseModel):
    name: str
    status: str
    summary: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class RepairRecord(BaseModel):
    incident_id: str
    target: str
    source: str
    status: str
    message: str
    pr_url: str | None = None
    record_json_path: str | None = None
    record_markdown_path: str | None = None
    repair_result: RepairResult | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    disposition: str | None = None
    decision_reason: str | None = None
    evidence: list[str] = Field(default_factory=list)
    tool_plan: list[str] = Field(default_factory=list)
    root_cause_type: str | None = None
    risk_level: str | None = None
    human_action_required: bool = False
    human_resolution_steps: list[str] = Field(default_factory=list)
