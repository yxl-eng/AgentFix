from __future__ import annotations

from agentfix.config import GuardrailSettings
from agentfix.incident_ingest import IncidentIngestor
from agentfix.repo_context import RepoContextCollector


def test_collect_prioritizes_non_python_log_path(tmp_path) -> None:
    repo = tmp_path / "node_repo"
    source = repo / "src" / "app.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "export function getUser(user) {\n"
        "  return user.profile.email;\n"
        "}\n",
        encoding="utf-8",
    )
    log_text = (
        "TypeError: Cannot read properties of undefined (reading 'profile')\n"
        "    at getUser (src/app.ts:2:15)\n"
    )
    incident = IncidentIngestor().parse_log(log_text, incident_id="node-type-error")
    context = RepoContextCollector(GuardrailSettings()).collect(repo, incident)

    assert context.candidate_files
    assert context.candidate_files[0].relative_path == "src/app.ts"
    assert "exact log path match" in context.candidate_files[0].reasons
