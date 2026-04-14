from __future__ import annotations

from app.formatter import label_count


def test_label_count_supports_strings() -> None:
    assert label_count("items=", "5") == "items=5"


def test_label_count_casts_ints() -> None:
    assert label_count("items=", 5) == "items=5"
