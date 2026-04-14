from __future__ import annotations

from agentfix.incident_ingest import IncidentIngestor


def test_parse_python_traceback(fixtures_root) -> None:
    ingestor = IncidentIngestor()
    incident = ingestor.from_file(fixtures_root / "logs" / "none_attr.log")

    assert incident.service_name == "user-api"
    assert incident.environment == "prod"
    assert incident.exception_type == "AttributeError"
    assert incident.exception_message == "'NoneType' object has no attribute 'profile'"
    assert incident.stack_frames[0].file_path.endswith("app/service.py")
    assert incident.stack_frames[0].line_number == 5
    assert "POST /v1/profile/email" in (incident.trigger_hint or "")
