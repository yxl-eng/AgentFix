from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentfix.config import AppConfig, TargetSettings
from agentfix.event_state import EventStateStore
from agentfix.feishu import FeishuNotifier
from agentfix.incident_ingest import IncidentIngestor
from agentfix.models import RepairEvent, RepairRecord, ToolCallRecord
from agentfix.repair_records import RepairRecordWriter

if TYPE_CHECKING:
    from agentfix.repair_orchestrator import RepairOrchestrator


class AgentProcessor:
    def __init__(
        self,
        *,
        config: AppConfig,
        orchestrator: RepairOrchestrator,
        state_store: EventStateStore | None = None,
        record_writer: RepairRecordWriter | None = None,
        notifier: FeishuNotifier | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.config = config
        self.orchestrator = orchestrator
        self.state_store = state_store or EventStateStore(config.server.state_path)
        self.record_writer = record_writer or RepairRecordWriter(config.records, project_root=project_root)
        self.notifier = notifier or FeishuNotifier(config.feishu)
        self.ingestor = IncidentIngestor()
        self._watch_offsets: dict[str, int] = {}

    def handle_incident_payload(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        forbidden = {"repo_path", "repo_url"} & set(payload)
        if forbidden:
            return {"status": "rejected", "reason": f"Unsupported fields: {', '.join(sorted(forbidden))}"}
        target_name = str(payload.get("target") or "")
        target_config = self.config.targets.get(target_name)
        if target_config is None:
            return {"status": "rejected", "reason": f"Unknown target: {target_name}"}
        event = RepairEvent(
            source="incident_webhook",
            target=target_name,
            log_text=str(payload.get("log_text") or ""),
            log_file=payload.get("log_file"),
            incident_id=payload.get("incident_id"),
            base_branch=payload.get("base_branch"),
            delivery_id=(headers or {}).get("X-AgentFix-Delivery"),
            request_context=payload.get("request_context"),
            expected_outcome=payload.get("expected_outcome"),
            raw_payload=payload,
        )
        return self.process_event(event, target_config)

    def handle_github_payload(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        headers = headers or {}
        if headers.get("X-GitHub-Event") not in {None, "issues"}:
            return {"status": "ignored", "reason": "Only GitHub issues events are supported."}
        action = payload.get("action")
        if action not in {"opened", "labeled"}:
            return {"status": "ignored", "reason": f"Ignored issue action: {action}"}
        issue = payload.get("issue") or {}
        labels = issue.get("labels") or []
        label_names = {str(label.get("name", "")).lower() for label in labels if isinstance(label, dict)}
        if "bug" not in label_names:
            return {"status": "ignored", "reason": "Issue does not have a bug label."}
        repo = payload.get("repository") or {}
        repo_full_name = repo.get("full_name")
        target_name, target_config = self._find_target_by_repo(repo_full_name)
        if target_config is None or target_name is None:
            return {"status": "ignored", "reason": f"No configured target for repository: {repo_full_name}"}
        issue_number = issue.get("number") or headers.get("X-GitHub-Delivery") or self._hash_text(json.dumps(payload))
        event = RepairEvent(
            source="github_issue",
            target=target_name,
            log_text=str(issue.get("body") or ""),
            incident_id=f"github-issue-{issue_number}",
            base_branch=target_config.base_branch,
            delivery_id=headers.get("X-GitHub-Delivery"),
            issue_url=issue.get("html_url"),
            issue_title=issue.get("title"),
            raw_payload=payload,
        )
        return self.process_event(event, target_config)

    def process_event(self, event: RepairEvent, target_config: TargetSettings) -> dict[str, Any]:
        event_key = self._event_key(event)
        if not self.state_store.claim(event_key):
            existing = self.state_store.get(event_key) or {}
            return {"status": "duplicate", "event_key": event_key, "existing": existing}

        tool_calls: list[ToolCallRecord] = []
        try:
            log_text = self._read_log(event, target_config)
            incident_id = event.incident_id or self._hash_text(f"{event.target}:{log_text}")[:12]
            tool_calls.append(
                ToolCallRecord(
                    name="Read Log",
                    status="success",
                    summary=f"Read {len(log_text)} log characters.",
                    inputs={"source": event.source, "target": event.target, "log_file": event.log_file},
                    outputs={"incident_id": incident_id},
                )
            )
            incident = self.ingestor.parse_log(log_text, incident_id=incident_id)
            incident.request_context = event.request_context
            incident.expected_outcome = event.expected_outcome
            result = self.orchestrator.run_incident(
                target_config.repo_path,
                incident,
                base_branch=event.base_branch or target_config.base_branch,
                publish=True,
                target_config=target_config,
            )
            if result.validation is not None and not result.validation.tests_executed and result.status == "validated":
                result.status = "needs_human_verification"
            tool_calls.extend(self._tool_calls_from_result(result))

            record = RepairRecord(
                incident_id=incident_id,
                target=event.target,
                source=event.source,
                status=result.status,
                message=result.root_cause_summary,
                pr_url=result.pr_url,
                repair_result=result,
                tool_calls=tool_calls,
            )
            record = self.record_writer.write(record, commit=False)
            result.record_json_path = record.record_json_path
            result.record_markdown_path = record.record_markdown_path
            record.tool_calls.append(
                ToolCallRecord(
                    name="Record Repair",
                    status="success",
                    summary="Wrote repair JSON and Markdown records.",
                    outputs={
                        "json": record.record_json_path,
                        "markdown": record.record_markdown_path,
                    },
                )
            )
            notified, notification_summary = self.notifier.notify_repair(record)
            result.feishu_notified = notified
            record.tool_calls.append(
                ToolCallRecord(
                    name="Notify Feishu",
                    status="success" if notified else "skipped",
                    summary=notification_summary,
                )
            )
            record.repair_result = result
            record = self.record_writer.write(record, commit=True)

            payload = record.model_dump(mode="json")
            self.state_store.complete(event_key, result.status, payload)
            return {"status": result.status, "event_key": event_key, "record": payload}
        except Exception as exc:
            error_payload = {"error": str(exc), "target": event.target, "source": event.source}
            self.state_store.complete(event_key, "failed", error_payload)
            return {"status": "failed", "event_key": event_key, "reason": str(exc)}

    def initialize_watch_offsets(self) -> None:
        for target_name, target_config in self.config.targets.items():
            path = self._target_log_path(target_config)
            if path is not None and path.exists():
                self._watch_offsets[target_name] = path.stat().st_size

    def poll_once(self) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        for target_name, target_config in self.config.targets.items():
            path = self._target_log_path(target_config)
            if path is None or not path.exists():
                continue
            previous = self._watch_offsets.get(target_name, path.stat().st_size)
            current = path.stat().st_size
            if current < previous:
                previous = 0
            self._watch_offsets[target_name] = current
            if current <= previous:
                continue
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(previous)
                new_text = handle.read()
            if not self._looks_like_error(new_text):
                continue
            event = RepairEvent(
                source="log_watch",
                target=target_name,
                log_text=new_text,
                incident_id=f"watch-{target_name}-{self._hash_text(new_text)[:12]}",
            )
            responses.append(self.process_event(event, target_config))
        return responses

    def _tool_calls_from_result(self, result) -> list[ToolCallRecord]:
        candidate_targets = []
        if result.analysis is not None:
            candidate_targets = [target.path for target in result.analysis.candidate_targets]
        validation_commands = []
        if result.validation is not None:
            validation_commands = [command.model_dump(mode="json") for command in result.validation.commands]
        generated_test_outputs = {}
        if result.generated_test is not None:
            generated_test_outputs = result.generated_test.model_dump(mode="json")
        return [
            ToolCallRecord(
                name="Read Code",
                status="success" if candidate_targets else "warning",
                summary="Collected candidate source files for model analysis.",
                outputs={"candidate_targets": candidate_targets, "changed_files": result.changed_files},
            ),
            ToolCallRecord(
                name="Detect Test Framework",
                status="success" if generated_test_outputs.get("framework") else "skipped",
                summary="Detected the target repository test framework for generated regression tests.",
                outputs=generated_test_outputs,
            ),
            ToolCallRecord(
                name="Generate Regression Test",
                status=(
                    "success"
                    if generated_test_outputs.get("test_path") and not generated_test_outputs.get("fallback_reason")
                    else "skipped"
                ),
                summary=generated_test_outputs.get("fallback_reason") or "Generated an incident-specific regression test.",
                outputs=generated_test_outputs,
            ),
            ToolCallRecord(
                name="Run Generated Test Before Fix",
                status="success" if generated_test_outputs.get("prefix_failed") else "skipped",
                summary="Ran generated test before applying the repair patch.",
                outputs=generated_test_outputs,
            ),
            ToolCallRecord(
                name="Run Generated Test After Fix",
                status="success" if generated_test_outputs.get("postfix_passed") else "skipped",
                summary="Ran generated test after applying the repair patch.",
                outputs=generated_test_outputs,
            ),
            ToolCallRecord(
                name="Run Verification",
                status="success" if result.validation and result.validation.is_success else "failed",
                summary="Ran configured tests and service verification.",
                outputs={"commands": validation_commands},
            ),
            ToolCallRecord(
                name="Git Commit/PR",
                status="success" if result.pr_url else "warning",
                summary="Created Draft PR." if result.pr_url else (result.failure_reason or "PR was not created."),
                outputs={"pr_url": result.pr_url, "branch": result.branch},
            ),
        ]

    def _read_log(self, event: RepairEvent, target_config: TargetSettings) -> str:
        if event.log_text:
            return event.log_text
        if not event.log_file:
            raise ValueError("Event must include log_text or log_file.")
        repo_path = Path(target_config.repo_path).resolve()
        log_path = (repo_path / event.log_file).resolve()
        if not log_path.is_relative_to(repo_path):
            raise ValueError("log_file must stay inside the configured target repository.")
        return log_path.read_text(encoding="utf-8", errors="ignore")

    def _target_log_path(self, target_config: TargetSettings) -> Path | None:
        if not target_config.service_log_file:
            return None
        repo_path = Path(target_config.repo_path).resolve()
        path = (repo_path / target_config.service_log_file).resolve()
        if not path.is_relative_to(repo_path):
            return None
        return path

    def _event_key(self, event: RepairEvent) -> str:
        raw_key = event.delivery_id or event.incident_id
        if raw_key:
            return f"{event.source}:{event.target}:{raw_key}"
        return f"{event.source}:{event.target}:{self._hash_text(event.log_text)}"

    def _find_target_by_repo(self, repo_full_name: str | None) -> tuple[str | None, TargetSettings | None]:
        for target_name, target_config in self.config.targets.items():
            if target_config.repo_full_name == repo_full_name:
                return target_name, target_config
        return None, None

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _looks_like_error(self, text: str) -> bool:
        return any(marker in text for marker in ["Traceback", "Error", "Exception", "panic:", "FAILED"])


class AgentServer:
    def __init__(self, processor: AgentProcessor, host: str, port: int, watch: bool = False) -> None:
        self.processor = processor
        self.host = host
        self.port = port
        self.watch = watch
        self._server: ThreadingHTTPServer | None = None
        self._watch_stop = threading.Event()

    def serve_forever(self) -> None:
        handler = self._make_handler(self.processor)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        if self.watch:
            self.processor.initialize_watch_offsets()
            threading.Thread(target=self._watch_loop, daemon=True).start()
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._watch_stop.set()
        if self._server is not None:
            self._server.shutdown()

    def _watch_loop(self) -> None:
        while not self._watch_stop.is_set():
            self.processor.poll_once()
            self._watch_stop.wait(self.processor.config.server.poll_interval_seconds)

    def _make_handler(self, processor: AgentProcessor):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/health":
                    self._send_json({"status": "ok"})
                    return
                self._send_json({"status": "not_found"}, status=404)

            def do_POST(self) -> None:
                payload = self._read_json()
                headers = {key: value for key, value in self.headers.items()}
                if self.path == "/webhooks/incidents":
                    self._send_json(processor.handle_incident_payload(payload, headers=headers))
                    return
                if self.path == "/webhooks/github":
                    self._send_json(processor.handle_github_payload(payload, headers=headers))
                    return
                self._send_json({"status": "not_found"}, status=404)

            def log_message(self, format: str, *args: object) -> None:
                return

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0:
                    return {}
                body = self.rfile.read(length).decode("utf-8")
                return json.loads(body or "{}")

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        return Handler
