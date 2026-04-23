"""Deterministic uuid + property generation for bench2."""

from __future__ import annotations

import random
import uuid
from typing import Iterator


def uuid_for_id(n: int) -> tuple[int, int]:
    """Map a sequential integer to a deterministic 128-bit uuid split into (hi, lo) i64s."""
    rng = random.Random(n)
    u = uuid.UUID(int=rng.getrandbits(128))
    hi = (u.int >> 64) & ((1 << 63) - 1)
    lo = u.int & ((1 << 63) - 1)
    return hi, lo


def random_props(rng: random.Random) -> dict:
    """Small, deterministic property bag mimicking a CRM 'account' record."""
    return {
        "name": f"acct_{rng.randrange(10**9)}",
        "score": rng.randrange(0, 100),
        "active": rng.random() < 0.7,
        "region": rng.choice(["us", "eu", "apac", "latam"]),
    }


# 48 non-uuid keys: 18 strings + 15 ints + 10 floats + 5 booleans.
# Combined with the (uuid_hi, uuid_lo) pair this yields exactly 50 properties.
def random_props_50(rng: random.Random) -> dict:
    """Property bag matching a real CRM 'account' record at 50-prop scale.

    Returns 48 non-uuid keys (18 str + 15 int + 10 float + 5 bool). The
    caller is expected to also include `uuid_hi` and `uuid_lo` to reach
    50 total keys (matching the indexed composite key).
    """
    out: dict = {}
    for i in range(1, 19):
        out[f"str_{i:02d}"] = "".join(rng.choices(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", k=12))
    for i in range(1, 16):
        out[f"int_{i:02d}"] = rng.randrange(0, 1_000_000)
    for i in range(1, 11):
        out[f"float_{i:02d}"] = rng.random() * 100.0
    for i in range(1, 6):
        out[f"bool_{i:02d}"] = rng.random() < 0.5
    return out


def hub_star_pairs(num_nodes: int) -> Iterator[tuple[int, int]]:
    """Yield (hub_id, spoke_id) edges for the hub/star topology.

    Every 10th node is a hub connected to the next 9. With num_nodes=100_000 we
    get 10_000 hubs × 9 spokes = 90_000 edges, ~1 edge/node ratio.
    """
    for hub in range(0, num_nodes, 10):
        for offset in range(1, 10):
            spoke = hub + offset
            if spoke >= num_nodes:
                return
            yield hub, spoke
