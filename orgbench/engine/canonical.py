"""Step 2 (event generation) — canonical slot extraction.

The six canonical slots are the gold for T1 (cross-artifact slot consistency).
Extraction is purely rule-based over the validated scenario, so the gold is
deterministic — never an LLM judgement.

``expected_in`` records, per slot, which artifacts the slot is *expected* to
surface in. It drives principled NULL handling during scoring: a NULL in a
non-expected artifact is fine; a NULL in an expected one is a miss.
"""

from __future__ import annotations

from .models import CanonicalSlots, Event, Scenario

__all__ = ["extract_canonical", "SLOT_EXPECTED_CHANNELS"]

# which channel types each canonical slot is expected to surface in
SLOT_EXPECTED_CHANNELS: dict[str, set[str]] = {
    "issue": {"chat", "email", "meeting", "document", "ticket", "approval"},
    "decision": {"meeting", "document", "approval"},
    "responsible_actor": {"meeting", "document", "approval", "email"},
    "approval_status": {"approval", "document", "meeting"},
    "intended_audience": {"email", "document", "meeting"},
    "visibility_constraint": {"document", "email", "chat"},
}


def extract_canonical(event: Event) -> CanonicalSlots:
    """Extract the six canonical slots for ``event`` (deterministic)."""
    scn = event.scenario
    decision_text, actor = _final_decision(scn)
    return CanonicalSlots(
        issue=scn.title,
        decision=decision_text,
        responsible_actor=actor,
        approval_status=_approval_status(scn, event),
        intended_audience=_intended_audience(event),
        visibility_constraint=_visibility_constraint(scn),
        expected_in=_expected_in(event),
    )


def _final_decision(scn: Scenario) -> tuple[str, str]:
    """The latest decision = the event's primary decision."""
    if not scn.decisions:
        return "", ""
    primary = max(scn.decisions, key=lambda d: d.day)
    return primary.decision, primary.by


def _approval_status(scn: Scenario, event: Event) -> str:
    """Event-level approval slot. ``na`` when the event runs no formal
    approval process (so it is consistent with the per-item approval
    timeline); otherwise ``approved`` once a decision is reached, else
    ``under_review``."""
    if not event.involves_approval:
        return "na"
    return "approved" if scn.decisions else "under_review"


def _intended_audience(event: Event) -> str:
    """The event's intended audience — the union of the people its artifacts
    were shared with, read straight off the engine's artifact metadata.

    Derived from the metadata (recipients / channel members / attendees /
    sharing lists) rather than from a free-text scenario value, so the slot is
    consistent with the rendered surface by construction: every person named
    here genuinely appears on an artifact, and no artifact reaches anyone not
    listed (drift-added over-sharing is the failure, tracked separately)."""
    emps: set[str] = set()
    for a in event.artifacts:
        md = a.metadata
        emps |= set(md.channel_members or [])
        emps |= set(md.attendees or [])
        emps |= set(md.sharing_list or [])
        if md.recipients:
            for key in ("to", "cc", "bcc"):
                emps |= set(md.recipients.get(key, []))
    return ",".join(sorted(emps)) if emps else "event team only"


def _visibility_constraint(scn: Scenario) -> str:
    if not scn.restricted_facts:
        return "none"
    return "; ".join(scn.restricted_facts)


def _expected_in(event: Event) -> dict[str, list[str]]:
    """Map each slot to the artifact_ids it is expected to surface in.

    Requires ``event.artifacts`` to be planned already (Step 2 artifact planning).
    """
    expected: dict[str, list[str]] = {}
    for slot, channels in SLOT_EXPECTED_CHANNELS.items():
        expected[slot] = sorted(
            a.artifact_id for a in event.artifacts
            if a.channel_type in channels
            and _slot_available_in_artifact(slot, event, a)
        )
    _ensure_temporal_slot_coverage(event, expected)
    return expected


def _ensure_temporal_slot_coverage(
    event: Event, expected: dict[str, list[str]],
) -> None:
    """Guarantee final decision slots have at least one eligible surface.

    Some events reach their final decision in a late chat/email/ticket rather
    than a later meeting/document/approval artifact. In that case the strict
    channel prior would make the final decision unmeasurable for T1. Use the
    first artifacts at or after the final decision day as a deterministic
    fallback.
    """
    decisions = event.scenario.decisions if event.scenario else []
    if not decisions:
        return
    final_day = max(d.day for d in decisions)
    eligible = sorted(
        (a for a in event.artifacts
         if a.items and a.items[0].day >= final_day),
        key=lambda a: (a.items[0].day, a.artifact_id),
    )
    fallback = [a.artifact_id for a in eligible[:2]]
    for slot in ("decision", "responsible_actor"):
        if not expected.get(slot) and fallback:
            expected[slot] = fallback


def _slot_available_in_artifact(slot: str, event: Event, artifact) -> bool:
    """Whether an artifact is temporally eligible to express a canonical slot.

    The canonical decision/responsible actor are the final decision and its
    actor, so artifacts before that decision day should not be expected to
    surface them. This keeps early meetings that correctly say "no decision
    yet" from being scored as misses for the final decision.
    """
    if slot not in {"decision", "responsible_actor", "approval_status"}:
        return True
    if slot == "approval_status" and not event.involves_approval:
        return True
    decisions = event.scenario.decisions if event.scenario else []
    if not decisions:
        return True
    final_day = max(d.day for d in decisions)
    if not artifact.items:
        return True
    art_day = artifact.items[0].day
    return art_day >= final_day
