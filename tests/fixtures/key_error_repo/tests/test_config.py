from __future__ import annotations

from app.config import read_user_id


def test_read_user_id_returns_value() -> None:
    assert read_user_id({"user_id": "42"}) == "42"


def test_read_user_id_returns_none_when_missing() -> None:
    assert read_user_id({}) is None
