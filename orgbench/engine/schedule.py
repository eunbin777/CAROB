"""Before Step 3 — meeting attendance / scheduling.

A corpus-wide pass over all planned meetings. People are busy: if someone is
invited to two meetings on the same day they cannot attend both, so the engine
marks them absent from one (a real cross-event scheduling conflict). A few
further absences are added at random — people miss meetings.

This only affects the *surface* (a meeting note says "X could not attend").
Authority audience is unchanged: an absent invitee still receives the notes.
"""

from __future__ import annotations

from .models import Event
from .rng import rng_for

__all__ = ["assign_attendance"]


def _artifact_day(artifact) -> int:
    return artifact.items[0].day if artifact.items else 0


def assign_attendance(events: list[Event], seed: int) -> dict:
    """Mark ``absent_actors`` on meeting artifacts. Returns a small report."""
    meetings = [a for ev in events for a in ev.artifacts
                if a.channel_type == "meeting"]

    # cross-event conflicts: an actor invited to 2+ meetings on one day
    booked: dict[tuple[str, int], list] = {}
    for a in meetings:
        day = _artifact_day(a)
        for emp in (a.metadata.attendees or []):
            booked.setdefault((emp, day), []).append(a)

    conflicts = 0
    for (emp, _day), arts in booked.items():
        if len(arts) > 1:
            # keep the actor in the first meeting, absent from the rest
            for a in sorted(arts, key=lambda x: x.artifact_id)[1:]:
                if emp not in a.absent_actors:
                    a.absent_actors.append(emp)
                    conflicts += 1

    # a few extra absences — people miss meetings even without a hard conflict
    random_absences = 0
    for a in meetings:
        invited = a.metadata.attendees or []
        present = [e for e in invited if e not in a.absent_actors]
        if len(present) >= 3:
            rng = rng_for(seed, "attendance", a.artifact_id)
            if rng.random() < 0.30:
                a.absent_actors.append(rng.choice(sorted(present)))
                random_absences += 1

    # Never leave a meeting structurally impossible. Conflicts can stack
    # across people and make every invitee absent, producing notes with an
    # empty attendee header but active discussion in the body (audit cases
    # event_028, event_068). And a single present attendee cannot hold a
    # discussion — we keep at least two present whenever the meeting was
    # planned with ≥ 2 invitees (the artifact_plan invariant guarantees ≥ 2).
    restored = 0
    for a in meetings:
        invited = list(a.metadata.attendees or [])
        if not invited:
            continue
        present = [e for e in invited if e not in a.absent_actors]
        need = 2 if len(invited) >= 2 else 1
        if len(present) >= need:
            continue
        # Restore absent invitees in sorted order until present >= need.
        to_restore: list[str] = []
        for e in sorted(invited):
            if e in a.absent_actors and (len(present) + len(to_restore)) < need:
                to_restore.append(e)
        if to_restore:
            a.absent_actors = [e for e in a.absent_actors if e not in to_restore]
            restored += len(to_restore)

    return {"meetings": len(meetings), "conflict_absences": conflicts,
            "random_absences": random_absences,
            "presence_restorations": restored}
