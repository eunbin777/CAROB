"""Corpus-level balancing helpers used during frame sampling.

Frame sampling makes many small categorical choices (drift type, AF code,
stress code, signal location). Left independent, these drift away from their
corpus-level targets on a small corpus. :class:`CorpusStats` accumulates
running counts so each new choice can be nudged toward the deficit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

__all__ = [
    "CorpusStats", "weighted_choice", "pick_underrepresented", "apportion",
]


@dataclass
class CorpusStats:
    """Running counts threaded through the per-event frame sampler."""

    event_types: dict[str, int] = field(default_factory=dict)
    drift_types: dict[str, int] = field(default_factory=dict)
    af_codes: dict[str, int] = field(default_factory=dict)
    stress_codes: dict[str, int] = field(default_factory=dict)

    def bump(self, bucket: str, key: str) -> None:
        d: dict[str, int] = getattr(self, bucket)
        d[key] = d.get(key, 0) + 1


def weighted_choice(weights: dict[str, float], rng: Random) -> str:
    """Pick one key with probability proportional to its weight."""
    keys = list(weights)
    total = sum(weights[k] for k in keys)
    r = rng.random() * total
    upto = 0.0
    for k in keys:
        upto += weights[k]
        if r <= upto:
            return k
    return keys[-1]


def pick_underrepresented(
    counts: dict[str, int], target_ratio: dict[str, float], rng: Random,
) -> str:
    """Pick the key whose current share is furthest *below* its target.

    When nothing has been counted yet, fall back to a weighted choice so the
    very first picks are not always the same key.
    """
    total = sum(counts.values())
    if total == 0:
        return weighted_choice(target_ratio, rng)
    deficits = {
        k: target_ratio[k] - counts.get(k, 0) / total
        for k in target_ratio
    }
    best = max(deficits.values())
    tied = sorted(k for k, v in deficits.items() if abs(v - best) < 1e-9)
    return rng.choice(tied)


def apportion(total: int, ratios: dict[str, float]) -> dict[str, int]:
    """Split ``total`` into integer counts per key (largest-remainder method)."""
    keys = list(ratios)
    weight_sum = sum(ratios[k] for k in keys)
    raw = {k: total * ratios[k] / weight_sum for k in keys}
    counts = {k: int(raw[k]) for k in keys}
    remainder = total - sum(counts.values())
    # hand out the remaining units to the largest fractional parts
    order = sorted(keys, key=lambda k: raw[k] - counts[k], reverse=True)
    for k in order[:remainder]:
        counts[k] += 1
    return counts
