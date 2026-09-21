"""Property tests for the fractional-indexing position generator.

Docmost orders pages by a base62 ``position`` compared lexicographically and
rejects anything outside 5-12 characters, which is stricter than a textbook
fractional-indexing implementation. These tests pin down the invariants that
matter, including the ones found the hard way against a real instance.

    uv run python tests/test_positions.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docmost_mcp_oss.position import (  # noqa: E402
    MAX_LENGTH,
    MIN_LENGTH,
    PositionError,
    first_key,
    key_between,
)

#: Positions Docmost actually assigned on a real instance.
REAL_POSITIONS = ["ZzBiT", "a04Nh", "a19lX", "a22tq", "a336b", "a4Bdv", "a54XP", "a26pA"]


def check(key: str, lower: str | None, upper: str | None) -> None:
    assert MIN_LENGTH <= len(key) <= MAX_LENGTH, f"{key!r} has length {len(key)}"
    assert set(key) <= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"), (
        f"{key!r} is outside the alphabet"
    )
    assert not key.endswith("0"), f"{key!r} ends in 0, which blocks later inserts"
    if lower is not None:
        assert key > lower, f"{key!r} does not sort after {lower!r}"
    if upper is not None:
        assert key < upper, f"{key!r} does not sort before {upper!r}"


def main() -> None:
    # A first key, then subsequent ones.
    seed = first_key()
    check(seed, None, None)
    assert key_between(seed) > seed
    print(f"✓ unbounded keys are usable (first is {seed!r})")

    # Every pair of positions a real instance produced.
    seen = 0
    for _ in range(3000):
        low, high = sorted(random.sample(REAL_POSITIONS, 2))
        check(key_between(low, high), low, high)
        seen += 1
    print(f"✓ {seen} intervals between real Docmost positions")

    # Half-open intervals.
    for position in REAL_POSITIONS:
        check(key_between(position), position, None)
        check(key_between(None, position), None, position)
    print("✓ half-open bounds (only a lower, only an upper)")

    # Narrow intervals that the naive padding approach could not fill. All three
    # are satisfiable, and were found by driving the real API.
    for low, high in (("a0", "a1000"), ("a0001", "a1000"), ("a00001", "a1000")):
        check(key_between(low, high), low, high)
    print("✓ narrow intervals that an earlier version failed to fill")

    # Repeated insertion into one gap must keep ordering until it is genuinely
    # saturated, and then fail with a clear message rather than a wrong key.
    low, high = key_between(), key_between(first_key())
    low, high = sorted((low, high))
    chain = 0
    try:
        for _ in range(5000):
            low = key_between(low, high)
            check(low, None, high)
            chain += 1
    except PositionError as exc:
        assert "gap is saturated" in str(exc), exc
        print(f"✓ subdividing one gap: {chain} inserts before it saturates")
    else:
        print(f"✓ subdividing one gap: {chain} inserts without saturating")

    # Ordering errors and bad input are reported, not papered over.
    for call, why in (
        (lambda: key_between("a19lX", "a04Nh"), "reversed bounds"),
        (lambda: key_between("nope!"), "character outside the alphabet"),
        (lambda: key_between(""), "empty position"),
        (lambda: key_between("a" * (MAX_LENGTH + 1)), "too long"),
    ):
        try:
            call()
        except PositionError:
            continue
        raise AssertionError(f"{why} was not rejected")
    print("✓ invalid input is rejected with PositionError")

    print("\nPosition generator verified.")


if __name__ == "__main__":
    main()
