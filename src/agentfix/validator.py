from __future__ import annotations

import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from agentfix.config import TargetSettings, ValidationSettings, VerificationRequestSettings
from agentfix.models import Incident, RepoContext, ValidationCommandResult, ValidationResult


class Validator:
    def validate(
        self,
        repo_path: str | Path,
        changed_files: list[str],
        repo_context: RepoContext,
        settings: ValidationSettings,
        target_config: TargetSettings | None = None,
        incident: Incident | None = None,
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
            target_config,
        )
        service_checks_configured = bool(
            target_config
            and (
                target_config.start_command
                or target_config.healthcheck_url
                or target_config.verification_requests
            )
        )
        if service_checks_configured and not test_commands:
            tests_skipped_reason = None
        tests_executed = bool(test_commands) or service_checks_configured
        tests_passed = True if tests_executed else None
        for command in test_commands:
            result = self._run(command, cwd=root)
            commands.append(result)
            if result.returncode != 0:
                tests_passed = False
                failures.append(f"Test command failed: {result.command}")

        if service_checks_configured and target_config is not None:
            service_results = self._run_service_verification(root, target_config, settings, incident)
            commands.extend(service_results)
            failed_service_results = [item for item in service_results if item.returncode != 0]
            if failed_service_results:
                tests_passed = False
                failures.extend(f"Service verification failed: {item.command}" for item in failed_service_results)

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
        target_config: TargetSettings | None = None,
    ) -> tuple[list[list[str] | str], str | None]:
        if target_config is not None and target_config.test_commands is not None:
            if target_config.test_commands:
                return target_config.test_commands, None
            return [], "Functional tests were skipped by target.test_commands configuration."
        if settings.test_commands is not None:
            if settings.test_commands:
                return settings.test_commands, None
            return [], "Functional tests were skipped by validation.test_commands configuration."
        if repo_context.metadata.test_candidates:
            return [[python_executable, "-m", "pytest", *repo_context.metadata.test_candidates]], None
        if (root / "tests").exists():
            return [[python_executable, "-m", "pytest"]], None
        return [], "No test targets were discovered; only syntax validation was run."

    def _run_service_verification(
        self,
        root: Path,
        target_config: TargetSettings,
        settings: ValidationSettings,
        incident: Incident | None,
    ) -> list[ValidationCommandResult]:
        results: list[ValidationCommandResult] = []
        service_process: subprocess.Popen[str] | None = None
        service_log_path = self._service_log_path(root, target_config)
        service_log_position = self._file_size(service_log_path)
        working_dir = (root / target_config.working_dir).resolve()
        if not working_dir.is_relative_to(root):
            return [
                ValidationCommandResult(
                    command=f"service working directory {target_config.working_dir}",
                    returncode=1,
                    stderr="Configured service working_dir escapes repository root.",
                )
            ]

        try:
            if target_config.start_command:
                try:
                    service_process = subprocess.Popen(
                        target_config.start_command,
                        cwd=working_dir,
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    results.append(
                        ValidationCommandResult(
                            command=f"start service: {target_config.start_command}",
                            returncode=0,
                            stdout=f"pid={service_process.pid}",
                        )
                    )
                    time.sleep(min(1.0, settings.service_start_timeout_seconds))
                    if service_process.poll() is not None and service_process.returncode != 0:
                        results.append(
                            ValidationCommandResult(
                                command=f"service process pid={service_process.pid}",
                                returncode=1,
                                stderr=f"Service exited early with {service_process.returncode}.",
                            )
                        )
                except OSError as exc:
                    results.append(
                        ValidationCommandResult(
                            command=f"start service: {target_config.start_command}",
                            returncode=1,
                            stderr=str(exc),
                        )
                    )
                    return results

            if target_config.healthcheck_url:
                results.append(
                    self._wait_for_healthcheck(
                        target_config.healthcheck_url,
                        timeout_seconds=settings.healthcheck_timeout_seconds,
                        interval_seconds=settings.healthcheck_interval_seconds,
                    )
                )

            for request in target_config.verification_requests:
                results.append(self._run_verification_request(request))

            if service_log_path is not None and incident is not None:
                results.append(self._scan_service_log(service_log_path, service_log_position, incident))
        finally:
            if service_process is not None:
                results.append(self._stop_service(service_process))
        return results

    def _wait_for_healthcheck(
        self,
        url: str,
        *,
        timeout_seconds: float,
        interval_seconds: float,
    ) -> ValidationCommandResult:
        deadline = time.monotonic() + timeout_seconds
        last_error = ""
        while time.monotonic() <= deadline:
            try:
                with urllib.request.urlopen(url, timeout=interval_seconds) as response:
                    status = response.getcode()
                    if 200 <= status < 400:
                        return ValidationCommandResult(
                            command=f"healthcheck {url}",
                            returncode=0,
                            stdout=f"HTTP {status}",
                        )
                    last_error = f"HTTP {status}"
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = str(exc)
            time.sleep(interval_seconds)
        return ValidationCommandResult(
            command=f"healthcheck {url}",
            returncode=1,
            stderr=last_error or "Healthcheck timed out.",
        )

    def _run_verification_request(self, request_config: VerificationRequestSettings) -> ValidationCommandResult:
        method = request_config.method.upper()
        payload = request_config.body.encode("utf-8") if request_config.body is not None else None
        request = urllib.request.Request(
            url=request_config.url,
            data=payload,
            headers=request_config.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=request_config.timeout_seconds) as response:
                status = response.getcode()
                body = response.read(500).decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            body = exc.read(500).decode("utf-8", errors="ignore")
            return ValidationCommandResult(
                command=f"{method} {request_config.url}",
                returncode=0 if exc.code == request_config.expected_status else 1,
                stdout=f"HTTP {exc.code}\n{body}",
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            return ValidationCommandResult(
                command=f"{method} {request_config.url}",
                returncode=1,
                stderr=str(exc),
            )
        return ValidationCommandResult(
            command=f"{method} {request_config.url}",
            returncode=0 if status == request_config.expected_status else 1,
            stdout=f"HTTP {status}\n{body}",
        )

    def _scan_service_log(
        self,
        service_log_path: Path,
        service_log_position: int,
        incident: Incident,
    ) -> ValidationCommandResult:
        if not service_log_path.exists():
            return ValidationCommandResult(
                command=f"scan service log {service_log_path}",
                returncode=0,
                stdout="Service log file was not created.",
            )
        with service_log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(service_log_position)
            new_text = handle.read()
        markers = [
            marker
            for marker in [incident.exception_type, incident.exception_message[:120]]
            if marker and marker != "UnknownError"
        ]
        repeated = any(marker in new_text for marker in markers)
        return ValidationCommandResult(
            command=f"scan service log {service_log_path}",
            returncode=1 if repeated else 0,
            stdout="No repeated incident markers found." if not repeated else "Incident marker repeated in service log.",
        )

    def _stop_service(self, process: subprocess.Popen[str]) -> ValidationCommandResult:
        if process.poll() is not None:
            return ValidationCommandResult(
                command=f"stop service pid={process.pid}",
                returncode=0,
                stdout=f"Process already exited with {process.returncode}.",
            )
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return ValidationCommandResult(
                command=f"stop service pid={process.pid}",
                returncode=0,
                stdout="Process killed after terminate timeout.",
            )
        return ValidationCommandResult(
            command=f"stop service pid={process.pid}",
            returncode=0,
            stdout="Process terminated.",
        )

    def _service_log_path(self, root: Path, target_config: TargetSettings) -> Path | None:
        if not target_config.service_log_file:
            return None
        path = (root / target_config.service_log_file).resolve()
        if not path.is_relative_to(root):
            return None
        return path

    def _file_size(self, path: Path | None) -> int:
        if path is None or not path.exists():
            return 0
        return path.stat().st_size

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
