"""Visibility-drift scheduling (frame stage).

A VisibilityDriftEvent widens who can see an item *after the fact*. Drift is
how the corpus realizes an AF5 (overbroad sharing) failure: the engine
schedules exactly one drift for an event whose committed ``af_codes`` contain
AF5, and none otherwise. At frame time only type / day / target_users are
fixed; the concrete ``origin`` item is bound later in Step 2, once the
scenario's audience_changes exist.
"""

from __future__ import annotations

from .models import Event, EventFrame, Organization, VisibilityDriftEvent
from .rng import rng_for
from .stats import CorpusStats, pick_underrepresented

__all__ = ["schedule_drift"]

_EFFECT = {
    "message_forwarding":
        "an email item is forwarded, widening its audience",
    "late_joiner_history":
        "a new member joins a chat channel; prior history may be shared",
    "document_sharing_expansion":
        "a document's sharing list is expanded to new recipients",
}


def schedule_drift(
    event: Event,
    frame: EventFrame,
    org: Organization,
    drift_ratio: dict[str, float],
    stats: CorpusStats,
    seed: int,
) -> list[VisibilityDriftEvent]:
    """Return the drift events for one event — one per committed AF5, else none."""
    n_drift = frame.af_codes.count("AF5")
    if n_drift == 0:
        return []

    rng = rng_for(seed, event.event_id, "drift")
    outsiders = [
        e.emp_id for e in org.employees
        if e.emp_id not in frame.candidate_actors
    ]
    drifts: list[VisibilityDriftEvent] = []
    for _ in range(n_drift):
        dtype = pick_underrepresented(stats.drift_types, drift_ratio, rng)
        stats.bump("drift_types", dtype)
        day = rng.randint(
            event.start_day + 1,
            max(event.start_day + 1, event.start_day + frame.duration_days - 1),
        )
        n_targets = rng.choice([1, 2])
        targets = (rng.sample(outsiders, min(n_targets, len(outsiders)))
                   if outsiders else [])
        drifts.append(VisibilityDriftEvent(
            drift_type=dtype,
            day=day,
            origin="",                       # bound later in Step 2
            target_users=targets,
            audience_effect=_EFFECT[dtype],
        ))
    return drifts
