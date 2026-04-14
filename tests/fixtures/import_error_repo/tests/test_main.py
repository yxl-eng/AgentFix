from __future__ import annotations

from app.main import greet


def test_greet_formats_name() -> None:
    assert greet(" codex ") == "Hello, Codex!"
