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
