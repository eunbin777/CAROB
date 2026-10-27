"""Step 2 — artifact and item planning.

Each scenario milestone produces a *cluster* of artifacts (the milestone's
ArtifactSpec list, written by the LLM). The engine turns each spec into a real
Artifact: it fixes the channel, binds chat artifacts to a standing team
channel (so the same channel recurs across milestones), plans item shells
(count, sender, day within the milestone window), and sets the deciding-cue
location. Step 3 only fills in item text.
"""

from __future__ import annotations

from .calendar import business_date
from .models import (
    CHANNEL_TYPES, TICKET_PRIORITIES, Artifact,
    ArtifactForm, ArtifactMetadata, Event, Item, Organization,
)
from .rng import rng_for
from .stats import weighted_choice

__all__ = ["plan_artifacts", "normalize_channel"]

# channel type -> (min, max) item count.
# Meeting and approval are fixed by their body schemas (4 and 3 sections);
# document and ticket are flexible (1 fixed preamble + N sections).
_ITEM_COUNT = {
    "chat": (3, 6), "email": (1, 3), "meeting": (4, 4),
    "document": (3, 5), "ticket": (2, 4), "approval": (3, 3),
}
_THREADED = {"chat", "email"}      # rendered item-by-item in Step 3

# Deciding-cue location distribution. Most artifacts are METADATA — the
# restriction is implicit in the recipient list, body stays neutral, which is
# how real internal artifacts mostly read. Explicit body cues are the
# deliberate minority. C1-stress events are the exception: C1 specifically
# tests "the authority signal is only in body text", so they stay body-heavy.
_CUE_DEFAULT = {"METADATA": 0.65, "BODY": 0.20, "TRANSITION_REF": 0.10,
                "BOTH": 0.05}
_CUE_C1 = {"BODY": 0.70, "TRANSITION_REF": 0.30}


def normalize_channel(raw: str) -> str:
    """Map an LLM-written channel string onto a known channel type."""
    s = (raw or "").strip().lower()
    if s in CHANNEL_TYPES:
        return s
    for key in ("chat", "email", "meeting", "document", "ticket", "approval"):
        if key in s:
            return key
    if "mail" in s:
        return "email"
    if "doc" in s or "note" in s:
        return "document"
    if "issue" in s:
        return "ticket"
    return "chat"


def plan_artifacts(event: Event, org: Organization) -> list[Artifact]:
    """Expand every milestone's ArtifactSpec cluster into real Artifacts.

    Each artifact happens on a single day, spread across its milestone's
    window; its items share that day. Threaded items also get rising HH:MM
    timestamps within the day.
    """
    seed = org.master_seed
    start_date = org.calendar.start_date
    milestones = event.scenario.milestones
    event_end = event.start_day + event.frame.duration_days
    artifacts: list[Artifact] = []

    for i, ms in enumerate(milestones):
        lo, hi = _milestone_window(milestones, i, event_end)
        actors = ms.actors or event.frame.candidate_actors
        n_arts = max(1, len(ms.artifacts))
        span = max(0, hi - lo)
        for j, spec in enumerate(ms.artifacts, start=1):
            channel = normalize_channel(spec.channel)
            # Meeting feasibility invariant: a meeting must have ≥ 2 invitees;
            # a one-person meeting is a planning bug (see event_054 in the
            # 2026-05-24 audit). When the milestone supplies only one actor we
            # pad from the event's candidate pool. If even that fails, downgrade
            # the channel to email — a one-actor "meeting" is not a meeting.
            channel, art_actors = _ensure_meeting_feasibility(
                channel, actors, event)
            artifact_id = f"{event.event_id}__m{i + 1}_a{j}_{channel}"
            # spread the cluster's artifacts across the milestone window
            art_day = min(hi, lo + (j - 1) * span // n_arts)
            metadata = _plan_metadata(channel, art_actors, event)
            form = _plan_form(channel, art_actors, event, artifact_id,
                              spec.summary, i, len(milestones), seed)
            _sync_form_metadata(channel, metadata, form)
            artifacts.append(Artifact(
                artifact_id=artifact_id,
                channel_type=channel,
                event_ids=[event.event_id],
                milestone_index=i,
                summary=spec.summary,
                channel_id=_channel_id(channel, art_actors, org, artifact_id, seed),
                deciding_cue_location=_cue_location(event, artifact_id, seed),
                items=_plan_items(artifact_id, channel, art_actors, art_day,
                                  start_date, seed),
                metadata=metadata,
                form=form,
            ))
    return artifacts


def _ensure_meeting_feasibility(
    channel: str, actors: list[str], event: Event,
) -> tuple[str, list[str]]:
    """Guarantee a meeting has at least two distinct invitees.

    A meeting with one invitee is a planning bug: surface fidelity falls
    apart because a one-person meeting cannot have a discussion, and the
    schedule pass can later mark that single invitee absent — producing
    the all-absent meeting (see event_028, event_054, event_068 in the
    2026-05-24 deep audit).

    Strategy: keep the milestone actors when possible; if fewer than two
    distinct people remain, pad from ``event.frame.candidate_actors``.
    The frame's candidate_actors is always sized ≥ 3 by
    :data:`_ACTOR_COUNT` (simple/moderate/complex → 3/5/7), so padding
    will always reach two; the function therefore never has to downgrade
    the channel.
    """
    if channel != "meeting":
        return channel, list(actors)
    invitees = _unique(actors)
    if len(invitees) < 2:
        pool = (event.frame.candidate_actors if event.frame else []) or []
        for emp_id in pool:
            if emp_id not in invitees:
                invitees.append(emp_id)
            if len(invitees) >= 2:
                break
    return "meeting", invitees


def _milestone_window(
    milestones: list, i: int, event_end: int,
) -> tuple[int, int]:
    """The [start, end] day range a milestone's artifacts live in."""
    start = milestones[i].day
    if i + 1 < len(milestones):
        end = max(start, milestones[i + 1].day - 1)
    else:
        end = max(start, event_end)
    return start, end


def _team_ids(org: Organization, actors: list[str]) -> list[str]:
    teams: set[str] = set()
    for emp_id in actors:
        try:
            teams.add(org.employee(emp_id).team_id)
        except KeyError:
            pass
    return sorted(teams)


def _channel_id(
    channel: str, actors: list[str], org: Organization,
    artifact_id: str, seed: int,
) -> str:
    """Chat artifacts bind to a standing team channel so the same channel
    recurs across milestones; other channels have no standing id."""
    if channel != "chat":
        return ""
    teams = _team_ids(org, actors)
    if not teams:
        return "C_org_all"
    return f"C_{rng_for(seed, artifact_id, 'channel').choice(teams)}"


def _cue_location(event: Event, artifact_id: str, seed: int) -> str:
    rng = rng_for(seed, artifact_id, "cue")
    sc = event.frame.stress_condition
    dist = _CUE_C1 if (sc and sc.code == "C1") else _CUE_DEFAULT
    return weighted_choice(dist, rng)


def _plan_items(
    artifact_id: str, channel: str, actors: list[str],
    day: int, start_date: str, seed: int,
) -> list[Item]:
    """All items of an artifact share its day; threaded items get rising
    HH:MM timestamps within that day."""
    lo, hi = _ITEM_COUNT[channel]
    rng = rng_for(seed, artifact_id, "items")
    n = rng.randint(lo, hi)
    iso = business_date(start_date, day)
    threaded = channel in _THREADED
    minute = rng.randint(8 * 60 + 30, 14 * 60)        # base time of day
    items: list[Item] = []
    for k in range(n):
        sender = actors[k % len(actors)] if threaded and actors else None
        items.append(Item(
            item_id=f"{artifact_id}::p{k + 1}",
            artifact_id=artifact_id,
            position=k,
            day=day,
            date=iso,
            time=f"{minute // 60:02d}:{minute % 60:02d}",
            sender=sender,
        ))
        if threaded:
            minute = min(minute + rng.randint(7, 38), 19 * 60)
    return items


def _plan_metadata(
    channel: str, actors: list[str], event: Event,
) -> ArtifactMetadata:
    members = _unique(actors)
    if channel == "chat":
        return ArtifactMetadata(
            channel_members=_with_min_participants(members, event, 2))
    if channel in ("email", "approval"):
        return ArtifactMetadata(
            recipients={"to": _with_min_participants(members, event, 2),
                        "cc": [], "bcc": []})
    if channel == "meeting":
        return ArtifactMetadata(attendees=members)
    if channel == "document":
        return ArtifactMetadata(sharing_list=members)
    if channel == "ticket":
        return ArtifactMetadata(
            project_visibility=event.project_id or "internal")
    return ArtifactMetadata()


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(a for a in ids if a))


def _with_min_participants(
    actors: list[str], event: Event, n: int,
) -> list[str]:
    """Add deterministic event actors when a threaded artifact has too few
    participants to make its visible header match the rendered conversation."""
    out = _unique(actors)
    if len(out) >= n:
        return out
    for emp_id in event.frame.candidate_actors:
        if emp_id not in out:
            out.append(emp_id)
        if len(out) >= n:
            break
    return out


def _sync_form_metadata(
    channel: str, metadata: ArtifactMetadata, form: ArtifactForm,
) -> None:
    """Keep deterministic form fields visible in the artifact metadata.

    This prevents the rendered surface from saying that someone prepared,
    reviewed, signed, or received an artifact while the channel metadata says
    they were outside that artifact's local audience.
    """
    if channel == "document":
        metadata.sharing_list = _unique(
            (metadata.sharing_list or []) + form.prepared_by + form.reviewed_by)
    elif channel == "approval":
        rcpt = metadata.recipients or {"to": [], "cc": [], "bcc": []}
        rcpt["to"] = _unique((rcpt.get("to") or [])
                             + ([form.approver] if form.approver else []))
        metadata.recipients = rcpt


def _plan_form(
    channel: str, actors: list[str], event: Event, artifact_id: str,
    summary: str, ms_idx: int, n_ms: int, seed: int,
) -> ArtifactForm:
    """Engine-set form fields, deterministic.

    LLM-set fields (``title``, ``doc_type``, ``issue_type``) are filled in
    later by the renderer from the body-schema JSON the LLM emits. The
    ``approval.approver`` here is a default actual signer; an AF4 binding may
    later force it to be distinct from the authorised approver. The
    ``approval.decision`` is populated from canonical at render time.
    """
    form = ArtifactForm()
    if channel == "email":
        form.subject = summary[:80]
    elif channel == "document":
        form.prepared_by = list(actors[:2])
        cand = [a for a in event.frame.candidate_actors
                if a not in form.prepared_by]
        form.reviewed_by = cand[:5]
    elif channel == "ticket":
        ev_seq = event.event_id.split("_")[-1]
        form.ticket_id = f"TKT-{ev_seq}-M{ms_idx + 1}A{artifact_id.split('_a')[1].split('_')[0]}"
        form.status = _ticket_status(ms_idx, n_ms)
        form.priority = weighted_choice(
            {p: 1.0 for p in TICKET_PRIORITIES},
            rng_for(seed, artifact_id, "priority"))
        form.assignee = actors[0] if actors else ""
    elif channel == "approval":
        form.approver = actors[0] if actors else ""
        # decision and final approver (after AF4 binding) finalised at render
    return form


def _ticket_status(ms_idx: int, n_ms: int) -> str:
    """Map a ticket's milestone position to a sensible status. A ticket in
    the first milestone reads as freshly opened; in the last milestone it
    reads as resolved; in between, work is in progress or in review."""
    if n_ms <= 1:
        return "open"
    if ms_idx == 0:
        return "open"
    if ms_idx == n_ms - 1:
        return "resolved"
    if ms_idx >= n_ms - 2:
        return "in_review"
    return "in_progress"
