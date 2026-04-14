from __future__ import annotations


class Order:
    def __init__(self, amount_cents: int) -> None:
        self.amount_cents = amount_cents


def get_total_cents(order: Order) -> int:
    return order.total_cents
