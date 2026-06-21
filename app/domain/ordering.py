"""LexoRank-style fractional ordering keys: base-36 strings read as fractions in (0, 1)."""

from __future__ import annotations

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE = len(DIGITS)


def _digit(s: str, i: int) -> int:
    return DIGITS.index(s[i]) if i < len(s) else 0


def between(low: str | None, high: str | None) -> str:
    low = low or ""
    high = high or ""
    if high and low >= high:
        raise ValueError(f"low {low!r} must sort before high {high!r}")

    result = []
    i = 0
    while True:
        lo = _digit(low, i)
        # Once past high's last digit, the upper bound opens up to the full base.
        hi = _digit(high, i) if i < len(high) else BASE
        mid = (lo + hi) // 2
        if mid > lo:
            result.append(DIGITS[mid])
            return "".join(result)
        result.append(DIGITS[lo])
        i += 1
