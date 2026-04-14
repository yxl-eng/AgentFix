from __future__ import annotations

from app.account import Order, get_total_cents


def test_get_total_cents_reads_amount() -> None:
    assert get_total_cents(Order(1250)) == 1250
