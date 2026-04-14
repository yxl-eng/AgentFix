from __future__ import annotations

from app.helpers import format_name


def greet(name: str) -> str:
    return f"Hello, {format_name(name)}!"
