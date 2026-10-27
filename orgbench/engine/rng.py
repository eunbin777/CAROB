"""Deterministic seed management.

Every random choice in the engine derives from a single ``master_seed``.
A sub-seed is computed from the master seed plus a tuple of string-able
"path" parts, so the same (master_seed, path) always yields the same RNG.

This keeps the whole engine reproducible: same master_seed -> same corpus
structure, independent of call order.

Example
-------
>>> rng = rng_for(20260526, "event_007", "complexity")
>>> rng.random()  # deterministic for this (seed, path)
"""

from __future__ import annotations

import hashlib
from random import Random

__all__ = ["sub_seed", "rng_for"]


def sub_seed(master: int, *parts: object) -> int:
    """Derive a stable 64-bit sub-seed from ``master`` and ``parts``.

    The path parts are joined into a single key and hashed; this means the
    derived seed depends only on the *values*, never on call order.
    """
    key = "::".join([str(master), *(str(p) for p in parts)])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def rng_for(master: int, *parts: object) -> Random:
    """Return a ``random.Random`` seeded deterministically for this path."""
    return Random(sub_seed(master, *parts))
