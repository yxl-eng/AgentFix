from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from agentfix.agent_server import AgentProcessor, AgentServer
from agentfix.config import AppConfig, load_config
from agentfix.event_state import EventStateStore
from agentfix.feishu import FeishuNotifier
from agentfix.generated_tests import FrameworkDetector, GeneratedTestAgent, GeneratedTestRunner, GeneratedTestValidator
from agentfix.incident_ingest import IncidentIngestor
from agentfix.patch_engine import PatchEngine
from agentfix.publisher import GitHubPublisher
from agentfix.providers.base import ModelProviderError, StructuredModelProvider
from agentfix.providers.openai_provider import OpenAIResponsesProvider
from agentfix.repair_records import RepairRecordWriter
from agentfix.repair_orchestrator import RepairOrchestrator
from agentfix.repo_context import RepoContextCollector
from agentfix.services.analysis import AnalysisAgent
from agentfix.services.patching import PatchAgent
from agentfix.validator import Validator


class UnavailableProvider(StructuredModelProvider):
    def generate_structured(
        self,
        *,
        instructions: str,
        prompt: str,
        output_model: type,
        reasoning_effort: str | None = None,
    ):
        raise ModelProviderError("This command path does not have a model provider configured.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent-based service auto-repair CLI for Python repositories")
    parser.add_argument("--config", default=None, help="Path to agentfix.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Show runtime configuration, agent topology, and credential presence")

    run_parser = subparsers.add_parser("run", help="Run the full repair pipeline")
    run_parser.add_argument("--repo", required=True, help="Path to the local repository")
    run_parser.add_argument("--log-file", required=True, help="Path to the incident log file")
    run_parser.add_argument("--base-branch", default="main", help="Base branch for the repair PR")
    run_parser.add_argument("--no-pr", action="store_true", help="Skip PR creation after validation")

    analyze_parser = subparsers.add_parser("analyze", help="Analyze incident and candidate files only")
    analyze_parser.add_argument("--repo", required=True, help="Path to the local repository")
    analyze_parser.add_argument("--log-file", required=True, help="Path to the incident log file")
    analyze_parser.add_argument("--base-branch", default="main", help="Base branch for context collection")

    validate_parser = subparsers.add_parser("validate", help="Validate an existing patch in a repository")
    validate_parser.add_argument("--repo", required=True, help="Path to the local repository")
    validate_parser.add_argument("--base-branch", default="main", help="Base branch for context collection")
    validate_parser.add_argument("--log-file", default=None, help="Optional incident log file for better test selection")
    validate_parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Changed files to validate. Defaults to git diff --name-only output.",
    )

    pr_parser = subparsers.add_parser("pr", help="Create a Draft PR for the current branch")
    pr_parser.add_argument("--repo", required=True, help="Path to the local repository")
    pr_parser.add_argument("--base-branch", default="main", help="Base branch for the pull request")
    pr_parser.add_argument("--report-file", required=True, help="Path to repair-result.json")

    serve_parser = subparsers.add_parser("serve", help="Run the AgentFix webhook and watch service")
    serve_parser.add_argument("--host", default=None, help="Host to bind. Defaults to server.host from config")
    serve_parser.add_argument("--port", type=int, default=None, help="Port to bind. Defaults to server.port from config")
    serve_parser.add_argument("--watch", action="store_true", help="Enable configured service log polling")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    require_model = args.command in {"run", "analyze", "serve"}

    try:
        orchestrator = build_orchestrator(config, require_model=require_model)
    except ModelProviderError as exc:
        parser.error(str(exc))
        return 2

    if args.command == "doctor":
        print(_to_json(build_doctor_report(config, args.config)))
        return 0

    if args.command == "run":
        result = orchestrator.run(
            args.repo,
            args.log_file,
            base_branch=args.base_branch,
            publish=not args.no_pr,
        )
        print(_to_json(result.model_dump(mode="json")))
        return 0 if result.status in {"validated", "pr_created"} else 1

    if args.command == "analyze":
        result = orchestrator.analyze(args.repo, args.log_file, base_branch=args.base_branch)
        print(_to_json(result))
        return 0

    if args.command == "validate":
        changed_files = args.files or _git_changed_files(Path(args.repo))
        result = orchestrator.validate_existing(
            args.repo,
            changed_files=changed_files,
            log_file=args.log_file,
            base_branch=args.base_branch,
        )
        print(_to_json(result.model_dump(mode="json")))
        return 0 if result.is_success else 1

    if args.command == "pr":
        report_payload = json.loads(Path(args.report_file).read_text(encoding="utf-8"))
        branch = report_payload.get("branch") or _current_branch(Path(args.repo))
        title = f"[agentfix] {report_payload.get('root_cause_summary', 'Automated repair')}"
        validation_lines = "\n".join(
            f"- `{command}`" for command in report_payload.get("tests_run", [])
        ) or "- none"
        body = (
            "## Error Summary\n"
            f"- Status: `{report_payload.get('status', 'unknown')}`\n\n"
            "## Root Cause\n"
            f"{report_payload.get('root_cause_summary', 'n/a')}\n\n"
            "## Validation\n"
            f"{validation_lines}\n"
        )
        pr_result = orchestrator.publisher.create_pr_for_existing_branch(
            args.repo,
            branch=branch,
            base_branch=args.base_branch,
            title=title,
            body=body,
        )
        print(_to_json(pr_result.model_dump(mode="json")))
        return 0

    if args.command == "serve":
        host = args.host or config.server.host
        port = args.port or config.server.port
        processor = AgentProcessor(
            config=config,
            orchestrator=orchestrator,
            state_store=EventStateStore(config.server.state_path),
            record_writer=RepairRecordWriter(config.records),
            notifier=FeishuNotifier(config.feishu),
        )
        server = AgentServer(processor, host=host, port=port, watch=args.watch)
        print(_to_json({"status": "serving", "host": host, "port": port, "watch": args.watch}))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
        return 0

    parser.error("Unknown command")
    return 2


def build_orchestrator(config: AppConfig, *, require_model: bool = True) -> RepairOrchestrator:
    provider: StructuredModelProvider = build_provider(config) if require_model else UnavailableProvider()
    return RepairOrchestrator(
        config=config,
        ingestor=IncidentIngestor(),
        collector=RepoContextCollector(config.guardrails),
        analyzer=AnalysisAgent(provider, config),
        patch_agent=PatchAgent(provider, config),
        patch_engine=PatchEngine(),
        validator=Validator(),
        publisher=GitHubPublisher(config.github),
        generated_test_agent=GeneratedTestAgent(provider, config) if require_model else None,
        framework_detector=FrameworkDetector(),
        generated_test_runner=GeneratedTestRunner(),
        generated_test_validator=GeneratedTestValidator(),
    )


def build_provider(config: AppConfig) -> StructuredModelProvider:
    api_key = config.openai.resolved_api_key()
    if not api_key:
        raise ModelProviderError(
            f"Missing model API key. Set {config.openai.api_key_env_var} or add openai.api_key to agentfix.local.yaml."
        )
    return OpenAIResponsesProvider(
        model=config.openai.model,
        api_key=api_key,
        base_url=config.openai.base_url,
        transport=config.openai.transport,
    )


def _git_changed_files(repo: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _current_branch(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Unable to determine current git branch.")
    return completed.stdout.strip()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def build_doctor_report(config: AppConfig, config_path: str | None) -> dict[str, object]:
    return {
        "config_path": str(Path(config_path).resolve()) if config_path else str(Path("agentfix.yaml").resolve()),
        "agent_topology": {
            "orchestrator": "RepairOrchestrator",
            "analysis_agent": "AnalysisAgent",
            "patch_agent": "PatchAgent",
            "generated_test_agent": "GeneratedTestAgent",
            "validator": "Validator",
            "publisher": "GitHubPublisher",
            "model_provider": "OpenAIResponsesProvider",
            "agent_server": "AgentServer",
        },
        "workflow": [
            "ingest incident log",
            "collect repo context",
            "analysis agent produces root cause and candidate files",
            "patch agent produces minimal file updates",
            "generated test agent can add incident-specific regression tests before publishing",
            "patch engine enforces guardrails",
            "validator runs py_compile and optional pytest",
            "publisher creates branch, commit, push, and GitHub Draft PR",
            "agent server accepts incident and GitHub webhooks, writes repair records, and notifies Feishu",
        ],
        "configuration": {
            "default_model": config.openai.model,
            "base_url": config.openai.base_url,
            "transport": config.openai.transport,
            "analysis_reasoning_effort": config.openai.analysis_reasoning_effort,
            "patch_reasoning_effort": config.openai.patch_reasoning_effort,
            "validation_python": config.validation.resolved_python_executable(),
            "max_changed_files": config.guardrails.max_changed_files,
            "max_patch_lines": config.guardrails.max_patch_lines,
            "server_host": config.server.host,
            "server_port": config.server.port,
            "targets": sorted(config.targets),
            "generated_tests_enabled_targets": sorted(
                name for name, target in config.targets.items() if target.generated_tests.enabled
            ),
            "records_root": config.records.root,
        },
        "credentials": {
            "openai_api_key_env_var": config.openai.api_key_env_var,
            "openai_api_key_present": bool(config.openai.resolved_api_key()),
            "github_token_env_var": config.github.token_env_var,
            "github_token_present": bool(config.github.resolved_token()),
            "feishu_webhook_env_var": config.feishu.webhook_url_env_var,
            "feishu_webhook_present": bool(config.feishu.resolved_webhook_url()),
        },
        "runtime_checks": {
            "python_version": sys.version.split()[0],
            "modules": {
                "openai": _module_available("openai"),
                "pydantic": _module_available("pydantic"),
                "yaml": _module_available("yaml"),
                "pytest": _module_available("pytest"),
            },
        },
        "command_requirements": {
            "doctor": "no model key required",
            "validate": "no model key required",
            "pr": "requires GitHub token for actual PR creation",
            "analyze": "requires OpenAI API key",
            "run": "requires OpenAI API key and GitHub token unless --no-pr is used",
            "serve": "requires OpenAI API key, configured targets, and GitHub token for PR creation",
        },
    }


def _to_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)
