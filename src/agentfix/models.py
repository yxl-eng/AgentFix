from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class StackFrame(BaseModel):
    file_path: str
    line_number: int
    function_name: str
    code_line: str | None = None
    raw_frame: str | None = None


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


class ValidationResult(BaseModel):
    syntax_check: bool
    tests_passed: bool | None = None
    tests_executed: bool = False
    tests_skipped_reason: str | None = None
    commands: list[ValidationCommandResult] = Field(default_factory=list)
    failure_summary: list[str] = Field(default_factory=list)
    suggested_follow_up: list[str] = Field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.syntax_check and self.tests_passed is not False


class PullRequestResult(BaseModel):
    branch: str
    commit_sha: str
    pr_url: str
    title: str
    body: str


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
