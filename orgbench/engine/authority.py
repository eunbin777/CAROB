"""Per-item authority derivation (deterministic engine step).

Runs after artifacts are planned and rendered. For every item it builds an
:class:`AuthorityState` along three time-indexed dimensions:

  - audience_timeline: base audience (from artifact metadata) plus expansions
    from the event's drift events.
  - approval_timeline: in an event that runs a formal approval process, a
    reviewable deliverable (document / approval record) is ``under_review``
    from creation and becomes ``approved`` on the event's decision day,
    carrying the approver. Non-deliverables, and deliverables of events that
    conclude without a formal sign-off, are ``na``.
  - lifecycle_timeline: an item is ``current`` from creation; in an event
    that carries an AF2 (stale-state) failure the superseded deliverable
    transitions to ``superseded`` when its revision appears.

All three are derived by closed-form rules from the frozen scenario
(decisions, authority-failure days) and the engine's artifact plan — never
from rendered artifact text.
"""

from __future__ import annotations

from .models import (
    DRIFT_CHANNEL, ApprovalEntry, AudienceEntry, AudienceSpec, AuthorityState,
    Event, LifecycleEntry, Organization, VisibilityDriftEvent,
)
from .rng import rng_for

__all__ = ["derive_authority", "bind_drift_artifacts",
           "bind_authority_failures", "bind_af4_expected"]

# artifact channels whose items carry a reviewable deliverable — these are the
# items for which approval and lifecycle state genuinely evolve
_REVIEWABLE = ("document", "approval")


def derive_authority(event: Event, org: Organization) -> None:
    """Fill ``item.authority`` for every item — audience, approval, lifecycle."""
    decision_day, approver = _primary_decision(event)
    approval_event = event.involves_approval     # portfolio-declared
    superseded = _supersession_map(event)

    for artifact in event.artifacts:
        base = _base_audience(artifact, event)
        for item in artifact.items:
            item.authority = AuthorityState(
                item_id=item.item_id,
                audience_timeline=[AudienceEntry(item.day, base)],
                approval_timeline=_approval_timeline(
                    artifact, item, decision_day, approver, approval_event),
                lifecycle_timeline=_lifecycle_timeline(
                    artifact, item, superseded),
            )
    bind_drift_artifacts(event, org)
    for drift in event.frame.drift_events:
        _apply_drift(event, drift)
    bind_af4_expected(event, org)


def bind_af4_expected(event: Event, org: Organization) -> None:
    """For each AF4 (wrong reviewer), record the authorised approver so that
    'wrong reviewer' is a comparison of the actual approver against an
    engine-owned label rather than a judgement re-read from rendered text."""
    if not event.scenario:
        return
    af4s = [a for a in event.scenario.authority_failures
            if a.af_code == "AF4"]
    if not af4s:
        return
    if event.canonical and event.canonical.responsible_actor:
        for af in af4s:
            af.expected = event.canonical.responsible_actor
        return
    decisions = event.scenario.decisions if event.scenario else []
    _decision_day, decision_actor = _primary_decision(event)
    if decision_actor and len(decisions) > 1:
        for af in af4s:
            af.expected = decision_actor
        return
    team_of = {e.emp_id: e.team_id for e in org.employees}
    teams = [team_of[a] for a in event.frame.candidate_actors
             if a in team_of]
    if not teams:
        return
    primary = max(set(teams), key=teams.count)
    lead = next((t.lead_emp_id for t in org.teams
                 if t.team_id == primary), "")
    for af in af4s:
        af.expected = lead


# --- approval -------------------------------------------------------------

def _primary_decision(event: Event) -> tuple[int | None, str | None]:
    """Day and actor of the event's primary (latest) decision, if any."""
    decisions = event.scenario.decisions if event.scenario else []
    if not decisions:
        return None, None
    primary = max(decisions, key=lambda d: d.day)
    return primary.day, (primary.by or None)


def _approval_timeline(
    artifact, item, decision_day: int | None, approver: str | None,
    approval_event: bool,
) -> list[ApprovalEntry]:
    """In an approval event a reviewable deliverable moves ``under_review``
    -> ``approved`` on the decision day; everything else (non-deliverables,
    and all deliverables of a non-approval event) is ``na``.

    The approver is recorded on the ``approved`` entry: whether that actor was
    an authorised reviewer is exactly what an AF4 (wrong reviewer) turns on.
    """
    if artifact.channel_type not in _REVIEWABLE or not approval_event:
        return [ApprovalEntry(item.day, "na")]
    if decision_day is None:                       # no decision was reached
        return [ApprovalEntry(item.day, "under_review")]
    if item.day < decision_day:
        return [ApprovalEntry(item.day, "under_review"),
                ApprovalEntry(decision_day, "approved", actor=approver)]
    return [ApprovalEntry(item.day, "approved", actor=approver)]


# --- lifecycle ------------------------------------------------------------

def _supersession_map(event: Event) -> dict[str, tuple[int, str]]:
    """In an AF2 (stale-state) event the earliest reviewable deliverable is
    superseded by the next one. Returns artifact_id -> (from_day, by_item_id).
    Non-AF2 events have no supersession (nothing went stale)."""
    if (not event.frame or not event.scenario
            or "AF2" not in event.frame.af_codes):
        return {}
    reviewables = sorted(
        (a for a in event.artifacts
         if a.channel_type in _REVIEWABLE and a.items),
        key=lambda a: a.items[0].day)
    if not reviewables:
        return {}
    earliest = reviewables[0]
    if len(reviewables) >= 2:
        nxt = reviewables[1]
        return {earliest.artifact_id: (nxt.items[0].day, nxt.items[0].item_id)}
    # a single deliverable: it goes stale on the day the AF2 manifests
    af2_day = next((af.day for af in event.scenario.authority_failures
                    if af.af_code == "AF2"), 0)
    if af2_day > earliest.items[0].day:
        return {earliest.artifact_id: (af2_day, "")}
    return {}


def _lifecycle_timeline(
    artifact, item, superseded: dict[str, tuple[int, str]],
) -> list[LifecycleEntry]:
    """``current`` from creation; ``superseded`` once a revision replaces it."""
    timeline = [LifecycleEntry(item.day, "current")]
    sup = superseded.get(artifact.artifact_id)
    if sup:
        sup_day, by_item = sup
        if sup_day > item.day:
            timeline.append(LifecycleEntry(
                sup_day, "superseded", superseded_by=by_item or None))
    return timeline


# --- audience: base + drift ----------------------------------------------

def _base_audience(artifact, event: Event) -> AudienceSpec:
    """Who can see this artifact at creation — from its channel metadata."""
    md = artifact.metadata
    emps: list[str] = []
    if artifact.channel_type == "chat" and md.channel_members:
        emps = md.channel_members
    elif artifact.channel_type in ("email", "approval") and md.recipients:
        emps = (md.recipients.get("to", []) + md.recipients.get("cc", [])
                + md.recipients.get("bcc", []))
    elif artifact.channel_type == "meeting" and md.attendees:
        emps = md.attendees
    elif artifact.channel_type == "document" and md.sharing_list:
        emps = md.sharing_list
    if not emps:                                   # ticket, or missing metadata
        emps = event.frame.candidate_actors
    return AudienceSpec(include_emps=sorted(set(emps)))


def bind_drift_artifacts(event: Event, org: Organization) -> None:
    """Bind each drift event to the concrete artifact it happens on.

    Deterministic and idempotent: a drift that already has an ``origin`` is
    left as is. Run once before Step 3 rendering, so the renderer can write the
    drift moment into that artifact, and again before authority derivation
    as a safety net.

    Selection policy (time-aware, deterministic — replaces the older
    purely-random pick that could place a drift on an artifact whose
    items are dated *after* the drift day):

      1. If the scenario LLM already named ``drift.origin``, honour it.
      2. Otherwise restrict to artifacts of the drift's expected channel
         (``DRIFT_CHANNEL``); fall back to any artifact in the event if
         the channel match is empty.
      3. Prefer an artifact whose first item is dated on or before
         ``drift.day`` — forwarding / late-join / sharing-list expansion
         must happen on an artifact that already exists. Among those,
         take the one closest to ``drift.day`` (the most recently
         visible candidate). Tie-break by ``artifact_id`` so the choice
         is reproducible.
      4. If no eligible candidate exists (the drift day precedes every
         in-channel artifact), fall back to the earliest candidate and
         pull ``drift.day`` forward to that artifact's first-item day,
         preserving the invariant ``drift.day >= origin first item day``.

    The late-joiner-history coin-flip is settled here too, since it is a
    per-join decision rather than a fixed channel rule.
    """
    def _first_day(a):
        return min((it.day for it in a.items), default=10**9)

    for drift in event.frame.drift_events:
        if drift.origin:                           # scenario-LLM-named, honour
            continue
        want = DRIFT_CHANNEL.get(drift.drift_type)
        candidates = [a for a in event.artifacts
                      if a.channel_type == want] or list(event.artifacts)
        if not candidates:
            continue
        eligible = [a for a in candidates if _first_day(a) <= drift.day]
        if eligible:
            artifact = max(eligible,
                           key=lambda a: (_first_day(a), a.artifact_id))
        else:
            artifact = min(candidates,
                           key=lambda a: (_first_day(a), a.artifact_id))
            # forward cannot precede the artifact's existence: pull the
            # drift day forward to the artifact's first item.
            drift.day = _first_day(artifact)
        drift.origin = artifact.artifact_id
        # late_joiner_history: whether the joiner is given prior history is
        # a per-join decision, less likely on a restricted-visibility
        # channel (its members are more guarded).
        if drift.drift_type == "late_joiner_history":
            channel = next((c for c in org.channels
                            if c.channel_id == artifact.channel_id), None)
            restricted = (bool(channel)
                          and channel.default_visibility == "restricted")
            share_p = 0.35 if restricted else 0.60
            roll = rng_for(org.master_seed, event.event_id,
                           "history_shared", drift.day).random()
            drift.history_shared = roll < share_p


# channel types best suited to dramatize each non-drift authority failure
_AF_CHANNEL = {
    "AF1": ("email", "document"),          # wrong audience — a recipient list
    "AF2": ("document", "email", "meeting"),  # stale — a referenced document
    "AF3": ("chat", "email", "meeting"),   # premature signoff — a discussion
    "AF4": ("approval", "document"),       # wrong reviewer — an approval record
}


def _described_channel(af) -> str:
    desc = (af.description or "").lower()
    for word, channel in (
        ("chat", "chat"),
        ("email", "email"),
        ("meeting", "meeting"),
        ("document", "document"),
        ("approval", "approval"),
    ):
        if word in desc:
            return channel
    return ""


def bind_authority_failures(event: Event) -> None:
    """Bind each non-drift authority failure (AF1–AF4) to the concrete
    artifact that should dramatize it, so the Step 3 renderer can surface it.

    Deterministic and idempotent. AF5 is realized as a visibility drift and
    bound by :func:`bind_drift_artifacts` instead. The chosen artifact is the
    one whose day is closest to the failure day, preferring a channel suited
    to the failure kind — this is what lets the renderer turn the scenario's
    failure description into visible workplace friction."""
    if not event.scenario or not event.artifacts:
        return
    for af in event.scenario.authority_failures:
        if af.af_code == "AF5" or af.origin:
            continue
        prefer = _AF_CHANNEL.get(af.af_code, ())
        described = _described_channel(af)
        if described:
            prefer = (described,)
        pool = [a for a in event.artifacts
                if a.channel_type in prefer] or list(event.artifacts)
        artifact = min(pool, key=lambda a: (
            abs((a.items[0].day if a.items else 0) - af.day), a.artifact_id))
        af.origin = artifact.artifact_id


def _apply_drift(event: Event, drift: VisibilityDriftEvent) -> None:
    """Widen the audience of the artifact this drift is bound to."""
    artifact = next((a for a in event.artifacts
                     if a.artifact_id == drift.origin), None)
    if not artifact:
        return
    open_history = (drift.history_shared
                    if drift.drift_type == "late_joiner_history" else True)
    hit_any = False
    for item in artifact.items:
        if _drift_hits_item(drift, item, open_history):
            _expand_item(item, drift.target_users, drift.day)
            hit_any = True
    # guarantee every drift lands: if the day windows did not overlap, widen
    # the item nearest the drift day so the drift always has an audience effect
    if not hit_any and artifact.items:
        nearest = min(artifact.items, key=lambda it: abs(it.day - drift.day))
        _expand_item(nearest, drift.target_users, drift.day)


def _drift_hits_item(
    drift: VisibilityDriftEvent, item, open_history: bool,
) -> bool:
    dt = drift.drift_type
    if dt == "message_forwarding":
        return item.day <= drift.day               # a snapshot is forwarded
    if dt == "document_sharing_expansion":
        return True                                # sharing list widened
    if dt == "late_joiner_history":
        return open_history or item.day >= drift.day
    return False


def _expand_item(item, target_users: list[str], drift_day: int) -> None:
    """Add ``target_users`` to an item's audience from the drift day on."""
    base = item.authority.audience_timeline[0].audience
    expanded = AudienceSpec(
        include_teams=list(base.include_teams),
        include_emps=sorted(set(base.include_emps) | set(target_users)),
        exclude_emps=list(base.exclude_emps),
    )
    if drift_day <= item.day:                      # item is born already-widened
        item.authority.audience_timeline[0] = AudienceEntry(item.day, expanded)
    else:
        item.authority.audience_timeline.append(
            AudienceEntry(drift_day, expanded))
