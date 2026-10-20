"""Small helpers shared by the read and write modules."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def shape(row: dict[str, Any], **renames: str) -> dict[str, Any]:
    """snake_case row -> the camelCase object the frontend types describe.

    `renames` maps a column name to the key the UI expects when a plain camelCase
    of the column would be wrong (txn_type -> type, verification_status -> verification).
    """
    return {renames.get(k) or camel(k): v for k, v in row.items()}


def inr(amount: float) -> str:
    """Rupees with Indian digit grouping, matching the frontend's inr(): 2400000 -> ₹24,00,000."""
    whole = int(Decimal(str(abs(amount))).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    digits = str(whole)
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join([*groups, tail]) if groups else tail
    return f"{'-' if amount < 0 else ''}₹{grouped}"


def num(value: float) -> str:
    """The shortest plain decimal for a float, as JavaScript would print it: 3.1 -> '3.1', 1e6 -> '1000000'."""
    return format(Decimal(repr(value)).normalize(), "f")
