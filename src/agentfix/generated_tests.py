from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from textwrap import dedent

from agentfix.config import AppConfig, TargetSettings, ValidationSettings
from agentfix.models import (
    AnalysisResult,
    GeneratedTestProposal,
    Incident,
    RepoContext,
    TestFrameworkInfo,
    ValidationCommandResult,
)
from agentfix.providers.base import StructuredModelProvider


GENERATED_TEST_INSTRUCTIONS = dedent(
    """
    You write focused regression tests for automated repair.
    Return only structured output that:
    - creates at most one test file
    - follows the repository's existing test style and framework
    - encodes the correct behavior after the incident is fixed
    - does not assert that the current exception should be raised
    - avoids network calls unless the existing tests already do them
    - keeps the test deterministic and local to the repository
    - returns an empty test_path if a reliable test cannot be generated
    """
).strip()


class FrameworkDetector:
    def detect(self, repo_path: str | Path, target_config: TargetSettings | None = None) -> TestFrameworkInfo:
        root = Path(repo_path).resolve()
        requested = "auto"
        if target_config is not None:
            requested = target_config.generated_tests.framework.lower()
        if requested and requested != "auto":
            return self._explicit(requested)

        package_json = root / "package.json"
        if package_json.exists():
            detected = self._detect_node(package_json)
            if detected.is_supported:
                return detected

        if (root / "go.mod").exists():
            return TestFrameworkInfo(language="go", framework="go-test", reason="Found go.mod.")

        if (root / "pom.xml").exists():
            return TestFrameworkInfo(language="java", framework="java-maven-junit", reason="Found pom.xml.")
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return TestFrameworkInfo(language="java", framework="java-gradle-junit", reason="Found Gradle build file.")

        detected_python = self._detect_python(root)
        if detected_python.is_supported:
            return detected_python

        return TestFrameworkInfo(reason="No supported test framework was detected.")

    def _explicit(self, requested: str) -> TestFrameworkInfo:
        aliases = {
            "pytest": ("python", "python-pytest"),
            "python-pytest": ("python", "python-pytest"),
            "unittest": ("python", "python-unittest"),
            "python-unittest": ("python", "python-unittest"),
            "jest": ("node", "node-jest"),
            "node-jest": ("node", "node-jest"),
            "vitest": ("node", "node-vitest"),
            "node-vitest": ("node", "node-vitest"),
            "mocha": ("node", "node-mocha"),
            "node-mocha": ("node", "node-mocha"),
            "go": ("go", "go-test"),
            "go-test": ("go", "go-test"),
            "maven": ("java", "java-maven-junit"),
            "java-maven-junit": ("java", "java-maven-junit"),
            "gradle": ("java", "java-gradle-junit"),
            "java-gradle-junit": ("java", "java-gradle-junit"),
        }
        if requested not in aliases:
            return TestFrameworkInfo(reason=f"Unsupported explicit framework: {requested}.")
        language, framework = aliases[requested]
        return TestFrameworkInfo(language=language, framework=framework, reason=f"Configured framework: {requested}.")

    def _detect_node(self, package_json: Path) -> TestFrameworkInfo:
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        text = json.dumps(data)
        if "vitest" in text:
            return TestFrameworkInfo(language="node", framework="node-vitest", reason="package.json mentions vitest.")
        if "jest" in text:
            return TestFrameworkInfo(language="node", framework="node-jest", reason="package.json mentions jest.")
        if "mocha" in text:
            return TestFrameworkInfo(language="node", framework="node-mocha", reason="package.json mentions mocha.")
        return TestFrameworkInfo(reason="package.json did not mention a supported test framework.")

    def _detect_python(self, root: Path) -> TestFrameworkInfo:
        pytest_markers = ["pytest.ini", "tox.ini", "setup.cfg"]
        if any((root / name).exists() and "pytest" in (root / name).read_text(encoding="utf-8", errors="ignore") for name in pytest_markers):
            return TestFrameworkInfo(language="python", framework="python-pytest", reason="Found pytest configuration.")
        for dependency_file in ["requirements.txt", "requirements-dev.txt", "pyproject.toml"]:
            path = root / dependency_file
            if path.exists() and "pytest" in path.read_text(encoding="utf-8", errors="ignore").lower():
                return TestFrameworkInfo(language="python", framework="python-pytest", reason=f"{dependency_file} mentions pytest.")

        tests_root = root / "tests"
        if tests_root.exists():
            test_files = list(tests_root.rglob("test_*.py")) + list(tests_root.rglob("*_test.py"))
            if test_files:
                contents = "\n".join(
                    path.read_text(encoding="utf-8", errors="ignore")[:2000]
                    for path in test_files[:5]
                )
                if "unittest" in contents and "pytest" not in contents:
                    return TestFrameworkInfo(language="python", framework="python-unittest", reason="Existing tests use unittest.")
                return TestFrameworkInfo(language="python", framework="python-pytest", reason="Found Python test files.")

        if any(root.rglob("*.py")):
            return TestFrameworkInfo(language="python", framework="python-pytest", reason="Found Python source files.")
        return TestFrameworkInfo(reason="No Python source files were found.")


class GeneratedTestAgent:
    def __init__(self, provider: StructuredModelProvider, config: AppConfig) -> None:
        self.provider = provider
        self.config = config

    def propose(
        self,
        incident: Incident,
        analysis: AnalysisResult,
        repo_context: RepoContext,
        framework: TestFrameworkInfo,
        feedback: list[str] | None = None,
    ) -> GeneratedTestProposal:
        prompt = self._build_prompt(incident, analysis, repo_context, framework, feedback or [])
        return self.provider.generate_structured(
            instructions=GENERATED_TEST_INSTRUCTIONS,
            prompt=prompt,
            output_model=GeneratedTestProposal,
            reasoning_effort=self.config.openai.patch_reasoning_effort,
        )

    def _build_prompt(
        self,
        incident: Incident,
        analysis: AnalysisResult,
        repo_context: RepoContext,
        framework: TestFrameworkInfo,
        feedback: list[str],
    ) -> str:
        candidate_blocks: list[str] = []
        for candidate in repo_context.candidate_files[:5]:
            candidate_blocks.append(
                "\n".join(
                    [
                        f"FILE: {candidate.relative_path}",
                        "```text",
                        candidate.full_content[:5000],
                        "```",
                    ]
                )
            )
        test_candidates = ", ".join(repo_context.metadata.test_candidates) or "none"
        dependency_files = ", ".join(repo_context.metadata.dependency_files) or "none"
        feedback_block = "\n".join(f"- {item}" for item in feedback) if feedback else "- none"
        request_context = incident.request_context.model_dump(mode="json") if incident.request_context else None
        expected_outcome = incident.expected_outcome.model_dump(mode="json") if incident.expected_outcome else None

        return dedent(
            f"""
            INCIDENT
            exception_type: {incident.exception_type}
            exception_message: {incident.exception_message}
            trigger_hint: {incident.trigger_hint or "unknown"}
            request_context: {json.dumps(request_context, ensure_ascii=False)}
            expected_outcome: {json.dumps(expected_outcome, ensure_ascii=False)}
            raw_log:
            ```text
            {incident.log_text[:6000]}
            ```

            ANALYSIS
            root_cause_summary: {analysis.root_cause_summary}
            repair_plan:
            {chr(10).join(f"- {step}" for step in analysis.repair_plan) if analysis.repair_plan else "- none"}
            validation_focus:
            {chr(10).join(f"- {item}" for item in analysis.validation_focus) if analysis.validation_focus else "- none"}

            TEST FRAMEWORK
            language: {framework.language}
            framework: {framework.framework}
            detection_reason: {framework.reason}
            existing_test_candidates: {test_candidates}
            dependency_files: {dependency_files}

            PREVIOUS FEEDBACK
            {feedback_block}

            SOURCE CONTEXT
            {chr(10).join(candidate_blocks) if candidate_blocks else "(no source context)"}

            TASK
            Generate one regression test file that fails before the fix and passes after the fix.
            Prefer a path under an existing tests directory. For Python pytest, prefer tests/test_agentfix_<topic>.py.
            For Python unittest, create a unittest.TestCase class in a test_*.py file.
            Return the full test file content. If no reliable test is possible, set test_path to null.
            """
        ).strip()


class GeneratedTestRunner:
    def run(
        self,
        repo_path: str | Path,
        proposal: GeneratedTestProposal,
        framework: TestFrameworkInfo,
        settings: ValidationSettings,
    ) -> ValidationCommandResult:
        command = self.build_command(repo_path, proposal, framework, settings)
        return self._run(command, Path(repo_path).resolve())

    def build_command(
        self,
        repo_path: str | Path,
        proposal: GeneratedTestProposal,
        framework: TestFrameworkInfo,
        settings: ValidationSettings,
    ) -> list[str] | str:
        if proposal.run_command:
            return self._normalize_model_command(proposal.run_command, framework, settings)
        test_path = (proposal.test_path or "").replace("\\", "/")
        python = settings.resolved_python_executable()
        if framework.framework == "python-pytest":
            return [python, "-m", "pytest", test_path]
        if framework.framework == "python-unittest":
            return [python, "-m", "unittest", test_path]
        if framework.framework == "node-vitest":
            return f"npm exec vitest run {self._quote(test_path)}"
        if framework.framework == "node-jest":
            return f"npm exec jest -- --runTestsByPath {self._quote(test_path)}"
        if framework.framework == "node-mocha":
            return f"npm exec mocha {self._quote(test_path)}"
        if framework.framework == "go-test":
            package_dir = self._go_package(test_path)
            test_name = f" -run {proposal.test_name}" if proposal.test_name else ""
            return f"go test {package_dir}{test_name}"
        if framework.framework == "java-maven-junit":
            return f"mvn -Dtest={self._java_test_name(proposal)} test"
        if framework.framework == "java-gradle-junit":
            runner = "gradlew.bat" if (Path(repo_path) / "gradlew.bat").exists() else "./gradlew"
            return f"{runner} test --tests {self._java_test_name(proposal)}"
        return [python, "-m", "pytest", test_path]

    def _run(self, command: list[str] | str, cwd: Path) -> ValidationCommandResult:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{cwd}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(cwd)
        )
        try:
            if isinstance(command, str):
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                display = command
            else:
                completed = subprocess.run(
                    command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                display = " ".join(command)
        except OSError as exc:
            return ValidationCommandResult(command=str(command), returncode=1, stderr=str(exc))
        return ValidationCommandResult(
            command=display,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _normalize_model_command(
        self,
        command: str | list[str],
        framework: TestFrameworkInfo,
        settings: ValidationSettings,
    ) -> str | list[str]:
        if framework.framework not in {"python-pytest", "python-unittest"}:
            return command
        parts = self._command_parts(command)
        if not parts:
            return command
        executable = Path(parts[0]).name.lower()
        python = settings.resolved_python_executable()
        if framework.framework == "python-pytest":
            if executable in {"pytest", "pytest.exe"}:
                return [python, "-m", "pytest", *parts[1:]]
            if self._is_python_executable(executable) and len(parts) >= 3 and parts[1:3] == ["-m", "pytest"]:
                return [python, "-m", "pytest", *parts[3:]]
        if framework.framework == "python-unittest":
            if executable in {"unittest", "unittest.exe"}:
                return [python, "-m", "unittest", *parts[1:]]
            if self._is_python_executable(executable) and len(parts) >= 3 and parts[1:3] == ["-m", "unittest"]:
                return [python, "-m", "unittest", *parts[3:]]
        return command

    def _command_parts(self, command: str | list[str]) -> list[str]:
        if isinstance(command, list):
            return [str(part) for part in command]
        try:
            return shlex.split(command, posix=False)
        except ValueError:
            return []

    def _is_python_executable(self, executable: str) -> bool:
        return executable in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}

    def _quote(self, value: str) -> str:
        return f'"{value}"' if " " in value else value

    def _go_package(self, test_path: str) -> str:
        parent = str(Path(test_path).parent).replace("\\", "/")
        return "./" + parent if parent and parent != "." else "."

    def _java_test_name(self, proposal: GeneratedTestProposal) -> str:
        if proposal.test_name:
            return proposal.test_name
        return Path(proposal.test_path or "AgentFixGeneratedTest.java").stem


class GeneratedTestValidator:
    INFRASTRUCTURE_FAILURE_MARKERS = [
        "syntaxerror",
        "indentationerror",
        "modulenotfounderror",
        "importerror",
        "cannot find module",
        "could not collect",
        "no tests ran",
        "unknown option",
    ]

    def is_prefix_failure_related(self, result: ValidationCommandResult, incident: Incident) -> bool:
        if result.returncode == 0:
            return False
        output = f"{result.stdout}\n{result.stderr}".lower()
        if any(marker in output for marker in self.INFRASTRUCTURE_FAILURE_MARKERS):
            return False
        markers = [incident.exception_type.lower(), incident.exception_message[:80].lower()]
        if any(marker and marker in output for marker in markers):
            return True
        return any(marker in output for marker in ["assert", "assertionerror", "expected", "actual"])
