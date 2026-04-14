from __future__ import annotations

import re
from pathlib import Path

from agentfix.models import Incident, StackFrame


FRAME_RE = re.compile(r'^\s*File "(?P<path>.+?)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
EXCEPTION_RE = re.compile(
    r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception)|AssertionError|RuntimeError|ValueError):\s*(?P<message>.*)$"
)


class IncidentIngestor:
    def from_file(self, path: str | Path) -> Incident:
        file_path = Path(path)
        return self.parse_log(
            file_path.read_text(encoding="utf-8"),
            incident_id=file_path.stem,
        )

    def parse_log(self, log_text: str, incident_id: str | None = None) -> Incident:
        lines = log_text.splitlines()
        frames = self._extract_frames(lines)
        exception_type, exception_message = self._extract_exception(lines)
        service_name = self._extract_tag(log_text, ["service", "svc", "app"]) or "unknown-service"
        environment = self._extract_tag(log_text, ["env", "environment"]) or "unknown"
        suspected_module = self._extract_suspected_module(frames)
        trigger_hint = self._extract_trigger_hint(lines)
        occurred_at = self._extract_occurred_at(log_text)

        return Incident(
            service_name=service_name,
            environment=environment,
            log_text=log_text,
            exception_type=exception_type,
            exception_message=exception_message,
            stack_frames=frames,
            suspected_module=suspected_module,
            trigger_hint=trigger_hint,
            incident_id=incident_id,
            occurred_at=occurred_at,
        )

    def placeholder(self, reason: str = "manual-validation") -> Incident:
        return Incident(
            service_name="unknown-service",
            environment="unknown",
            log_text=reason,
            exception_type="UnknownError",
            exception_message=reason,
            stack_frames=[],
            suspected_module=None,
            trigger_hint=reason,
        )

    def _extract_frames(self, lines: list[str]) -> list[StackFrame]:
        frames: list[StackFrame] = []
        for index, line in enumerate(lines):
            match = FRAME_RE.match(line)
            if not match:
                continue
            code_line = None
            if index + 1 < len(lines):
                candidate = lines[index + 1].strip()
                if candidate and not FRAME_RE.match(candidate) and not EXCEPTION_RE.match(candidate):
                    code_line = candidate
            frames.append(
                StackFrame(
                    file_path=match.group("path"),
                    line_number=int(match.group("line")),
                    function_name=match.group("func").strip(),
                    code_line=code_line,
                    raw_frame=line.strip(),
                )
            )
        return frames

    def _extract_exception(self, lines: list[str]) -> tuple[str, str]:
        for line in reversed(lines):
            match = EXCEPTION_RE.match(line.strip())
            if match:
                return match.group("type"), match.group("message")
        return "UnknownError", ""

    def _extract_tag(self, text: str, keys: list[str]) -> str | None:
        for key in keys:
            match = re.search(rf"{re.escape(key)}[=:]\s*([A-Za-z0-9_.-]+)", text)
            if match:
                return match.group(1)
        return None

    def _extract_suspected_module(self, frames: list[StackFrame]) -> str | None:
        if not frames:
            return None
        return Path(frames[-1].file_path).stem

    def _extract_trigger_hint(self, lines: list[str]) -> str | None:
        lead_in: list[str] = []
        for line in lines:
            if line.startswith("Traceback"):
                break
            if line.strip():
                lead_in.append(line.strip())
        if not lead_in:
            return None
        return " | ".join(lead_in[-3:])

    def _extract_occurred_at(self, text: str) -> str | None:
        match = re.search(
            r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?)",
            text,
        )
        if match:
            return match.group(1)
        return None
