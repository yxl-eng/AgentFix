from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


DEFAULT_CONFIG_FILE = Path("patchpilot.yaml")
DEFAULT_LOCAL_CONFIG_FILE = Path("patchpilot.local.yaml")
LEGACY_CONFIG_FILE = Path("agentfix.yaml")
LEGACY_LOCAL_CONFIG_FILE = Path("agentfix.local.yaml")


class OpenAISettings(BaseModel):
    model: str = "gpt-5.2"
    api_key_env_var: str = "OPENAI_API_KEY"
    api_key: str | None = None
    base_url: str | None = None
    transport: str = "auto"
    analysis_reasoning_effort: str = "medium"
    patch_reasoning_effort: str = "high"

    def resolved_api_key(self) -> str | None:
        return self.api_key or os.getenv(self.api_key_env_var)


class GitHubSettings(BaseModel):
    token_env_var: str = "GITHUB_TOKEN"
    token: str | None = None
    api_base_url: str = "https://api.github.com"

    def resolved_token(self) -> str | None:
        return self.token or os.getenv(self.token_env_var)


class GuardrailSettings(BaseModel):
    max_changed_files: int = 3
    max_patch_lines: int = 250
    min_confidence: float = 0.45
    ignored_paths: list[str] = Field(
        default_factory=lambda: [
            ".git",
            ".venv",
            ".pytest_cache",
            "__pycache__",
            "node_modules",
        ]
    )


class ValidationSettings(BaseModel):
    python_executable: str = "python"
    test_commands: list[str] | None = None
    service_start_timeout_seconds: float = 20.0
    healthcheck_timeout_seconds: float = 20.0
    healthcheck_interval_seconds: float = 1.0

    def resolved_python_executable(self) -> str:
        if self.python_executable != "python":
            return self.python_executable
        executable = Path(sys.executable)
        if executable.name.lower().startswith("python"):
            return str(executable)
        return self.python_executable


class RuntimeSettings(BaseModel):
    artifact_root: str = ".patchpilot-artifacts"
    max_repair_attempts: int = 3


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    poll_interval_seconds: float = 10.0
    state_path: str = ".patchpilot-state/events.sqlite3"


class VerificationRequestSettings(BaseModel):
    method: str = "GET"
    url: str
    expected_status: int = 200
    body: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 10.0


class GeneratedTestSettings(BaseModel):
    enabled: bool = True
    framework: str = "auto"
    commit_when_stable: bool = True
    failure_policy: Literal["continue_existing_validation", "needs_human_verification"] = (
        "continue_existing_validation"
    )
    fallback_to_v2_on_failure: bool | None = Field(default=None, exclude=True)
    require_prefix_failure: bool = True
    max_files: int = 1

    @model_validator(mode="after")
    def _map_legacy_fallback_policy(self) -> "GeneratedTestSettings":
        if self.fallback_to_v2_on_failure is not None:
            self.failure_policy = (
                "continue_existing_validation"
                if self.fallback_to_v2_on_failure
                else "needs_human_verification"
            )
        return self

    @property
    def should_continue_existing_validation(self) -> bool:
        return self.failure_policy == "continue_existing_validation"

    @property
    def should_require_human_verification(self) -> bool:
        return self.failure_policy == "needs_human_verification"


class PlannerSettings(BaseModel):
    enabled: bool = True
    max_steps: int = 6
    allowed_tools: list[str] = Field(
        default_factory=lambda: [
            "Read Log",
            "Inspect Config",
            "Check Runtime",
            "Search Similar Fixes",
            "Read Code",
            "Generate Regression Test",
            "Run Test",
            "Git Commit",
            "Record Repair",
            "Notify Feishu",
        ]
    )


class AgentRiskSettings(BaseModel):
    max_changed_files: int | None = None
    max_changed_lines: int | None = None


class AgentReportSettings(BaseModel):
    notify_on_ignored: bool = False
    notify_on_report_only: bool = True
    notify_on_needs_more_context: bool = True


class AgentSettings(BaseModel):
    planner: PlannerSettings = Field(default_factory=PlannerSettings)
    risk: AgentRiskSettings = Field(default_factory=AgentRiskSettings)
    report: AgentReportSettings = Field(default_factory=AgentReportSettings)


class TargetSettings(BaseModel):
    repo_full_name: str | None = None
    repo_path: str
    base_branch: str = "main"
    service_log_file: str | None = None
    start_command: str | None = None
    working_dir: str = "."
    healthcheck_url: str | None = None
    test_commands: list[str] | None = None
    verification_requests: list[VerificationRequestSettings] = Field(default_factory=list)
    generated_tests: GeneratedTestSettings = Field(default_factory=GeneratedTestSettings)


class FeishuSettings(BaseModel):
    webhook_url_env_var: str = "FEISHU_WEBHOOK_URL"
    webhook_secret_env_var: str = "FEISHU_WEBHOOK_SECRET"
    webhook_url: str | None = None
    webhook_secret: str | None = None

    def resolved_webhook_url(self) -> str | None:
        return self.webhook_url or os.getenv(self.webhook_url_env_var)

    def resolved_webhook_secret(self) -> str | None:
        return self.webhook_secret or os.getenv(self.webhook_secret_env_var)


class RecordsSettings(BaseModel):
    root: str = "records"
    auto_commit: bool = True


class AppConfig(BaseModel):
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    targets: dict[str, TargetSettings] = Field(default_factory=dict)
    feishu: FeishuSettings = Field(default_factory=FeishuSettings)
    records: RecordsSettings = Field(default_factory=RecordsSettings)

    def model_post_init(self, __context: Any) -> None:
        if self.agent.risk.max_changed_files is not None:
            self.guardrails.max_changed_files = self.agent.risk.max_changed_files
        if self.agent.risk.max_changed_lines is not None:
            self.guardrails.max_patch_lines = self.agent.risk.max_changed_lines


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in config file: {path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        config_data: dict[str, Any] = {}
        base_path = DEFAULT_CONFIG_FILE if DEFAULT_CONFIG_FILE.exists() else LEGACY_CONFIG_FILE
        if base_path.exists():
            config_data = _load_yaml(base_path)

        local_override = (
            DEFAULT_LOCAL_CONFIG_FILE
            if DEFAULT_LOCAL_CONFIG_FILE.exists()
            else LEGACY_LOCAL_CONFIG_FILE
        )
        if local_override.exists():
            config_data = _deep_merge(config_data, _load_yaml(local_override))

        return AppConfig.model_validate(config_data)
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    return AppConfig.model_validate(_load_yaml(config_path))
