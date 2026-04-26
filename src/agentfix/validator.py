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

        test_commands, tests_skipped_reason = self._infer_test_commands(
            root,
            repo_context,
            settings,
            python_executable,
        )
        tests_executed = bool(test_commands)
        tests_passed = True if tests_executed else None
        for command in test_commands:
            result = self._run(command, cwd=root)
            commands.append(result)
            if result.returncode != 0:
                tests_passed = False
                failures.append(f"Test command failed: {result.command}")

        return ValidationResult(
            syntax_check=syntax_check,
            tests_passed=tests_passed,
            tests_executed=tests_executed,
            tests_skipped_reason=tests_skipped_reason,
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
    ) -> tuple[list[list[str] | str], str | None]:
        if settings.test_commands is not None:
            if settings.test_commands:
                return settings.test_commands, None
            return [], "Functional tests were skipped by validation.test_commands configuration."
        if repo_context.metadata.test_candidates:
            return [[python_executable, "-m", "pytest", *repo_context.metadata.test_candidates]], None
        if (root / "tests").exists():
            return [[python_executable, "-m", "pytest"]], None
        return [], "No test targets were discovered; only syntax validation was run."

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
