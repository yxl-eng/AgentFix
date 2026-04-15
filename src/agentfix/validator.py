from __future__ import annotations

import subprocess
from pathlib import Path

from agentfix.config import ValidationSettings
from agentfix.models import RepoContext, ValidationCommandResult, ValidationResult


class Validator:
    def validate(
        self,
        repo_path: str | Path,
        changed_files: list[str],
        repo_context: RepoContext,
        settings: ValidationSettings,
    ) -> ValidationResult:
        root = Path(repo_path).resolve()
        commands: list[ValidationCommandResult] = []
        failures: list[str] = []
        python_executable = settings.resolved_python_executable()

        python_targets = [path for path in changed_files if path.endswith(".py")]
        syntax_check = True
        if python_targets:
            compile_result = self._run(
                [python_executable, "-m", "py_compile", *python_targets],
                cwd=root,
            )
            commands.append(compile_result)
            syntax_check = compile_result.returncode == 0
            if not syntax_check:
                failures.append("Python syntax validation failed.")

        test_commands = self._infer_test_commands(root, repo_context, settings, python_executable)
        tests_passed = True
        for command in test_commands:
            result = self._run(command, cwd=root)
            commands.append(result)
            if result.returncode != 0:
                tests_passed = False
                failures.append(f"Test command failed: {result.command}")

        return ValidationResult(
            syntax_check=syntax_check,
            tests_passed=tests_passed,
            commands=commands,
            failure_summary=failures,
            suggested_follow_up=(
                ["Review failing command output and retry with a narrower patch."]
                if failures
                else []
            ),
        )

    def _infer_test_commands(
        self,
        root: Path,
        repo_context: RepoContext,
        settings: ValidationSettings,
        python_executable: str,
    ) -> list[list[str] | str]:
        if settings.test_commands is not None:
            return settings.test_commands
        if repo_context.metadata.test_candidates:
            return [[python_executable, "-m", "pytest", *repo_context.metadata.test_candidates]]
        if (root / "tests").exists():
            return [[python_executable, "-m", "pytest"]]
        return []

    def _run(self, command: list[str] | str, cwd: Path) -> ValidationCommandResult:
        try:
            if isinstance(command, str):
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                display = command
            else:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                display = " ".join(command)
        except OSError as exc:
            return ValidationCommandResult(
                command=str(command),
                returncode=1,
                stderr=str(exc),
            )
        return ValidationCommandResult(
            command=display,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
