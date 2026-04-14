from __future__ import annotations

from agentfix.config import GuardrailSettings
from agentfix.incident_ingest import IncidentIngestor
from agentfix.repo_context import RepoContextCollector


def test_collect_prioritizes_traceback_file(temp_repo, fixtures_root) -> None:
    repo = temp_repo("none_attr_repo")
    incident = IncidentIngestor().from_file(fixtures_root / "logs" / "none_attr.log")
    collector = RepoContextCollector(GuardrailSettings())

    context = collector.collect(repo, incident)

    assert context.candidate_files
    assert context.candidate_files[0].relative_path == "app/service.py"
    assert "tests/test_service.py" in context.metadata.test_candidates
