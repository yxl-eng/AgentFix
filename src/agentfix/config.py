from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class OpenAISettings(BaseModel):
    model: str = "deepseek-v3-2-251201"
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

    def resolved_python_executable(self) -> str:
        if self.python_executable != "python":
            return self.python_executable
        executable = Path(sys.executable)
        if executable.name.lower().startswith("python"):
            return str(executable)
        return self.python_executable


class RuntimeSettings(BaseModel):
    artifact_root: str = ".agentfix-artifacts"
    max_repair_attempts: int = 2


class AppConfig(BaseModel):
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)


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
        default = Path("agentfix.yaml")
        if default.exists():
            config_data = _load_yaml(default)
            local_override = Path("agentfix.local.yaml")
            if local_override.exists():
                config_data = _deep_merge(config_data, _load_yaml(local_override))
            return AppConfig.model_validate(config_data)
        return AppConfig()
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    return AppConfig.model_validate(_load_yaml(config_path))
