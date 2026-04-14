from __future__ import annotations

import pytest

from agentfix.config import GuardrailSettings
from agentfix.models import FilePatch, PatchProposal
from agentfix.patch_engine import PatchEngine, PatchGuardrailError


def test_patch_engine_applies_minimal_patch(temp_repo) -> None:
    repo = temp_repo("key_error_repo")
    proposal = PatchProposal(
        summary="Use dict.get for missing keys.",
        patches=[
            FilePatch(
                path="app/config.py",
                reason="Prevent KeyError when user_id is absent.",
                updated_content=(
                    "from __future__ import annotations\n\n\n"
                    "def read_user_id(payload):\n"
                    '    return payload.get("user_id")\n'
                ),
            )
        ],
    )

    applied = PatchEngine().apply(
        repo,
        proposal,
        allowed_paths=["app/config.py"],
        guardrails=GuardrailSettings(),
    )

    assert applied.changed_files == ["app/config.py"]
    assert 'payload.get("user_id")' in (repo / "app" / "config.py").read_text(encoding="utf-8")
    assert "app/config.py" in applied.diff_text


def test_patch_engine_blocks_dependency_files(temp_repo) -> None:
    repo = temp_repo("key_error_repo")
    proposal = PatchProposal(
        summary="Bad dependency mutation",
        patches=[
            FilePatch(
                path="pyproject.toml",
                reason="Should never be allowed",
                updated_content="[project]\nname='bad'\n",
            )
        ],
    )

    with pytest.raises(PatchGuardrailError):
        PatchEngine().apply(
            repo,
            proposal,
            allowed_paths=["pyproject.toml"],
            guardrails=GuardrailSettings(),
        )
