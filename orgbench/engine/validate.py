"""Step 4 rule checks — deterministic validation of a rendered event.

Rule-based checks that need no LLM: structural soundness, label-surface
agreement that can be decided mechanically, and organization-roster
consistency. Known invented role titles (the renderer occasionally defaults
to standard corporate titles the org does not use) are scrubbed in place to
the real roster role; role terms with no clean mapping are flagged for the
Tier-2 judge to reword in context.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Event, Organization, ValidationIssue

__all__ = ["validate_structure", "check_roster", "check_actor_ids",
           "check_meeting_feasibility", "check_surface_gates",
           "check_form_metadata_consistency", "check_af4_surface",
           "check_artifact_references", "check_temporal_surface",
           "ROLE_ALIASES"]

# invented role title -> the org's actual role. The simulated org has team
# leads, not a C-suite; the renderer sometimes slips in standard titles.
ROLE_ALIASES = {
    "Chief Financial Officer": "Finance Lead",
    "Chief Technology Officer": "Engineering Lead",
    "Chief Information Security Officer": "Security Lead",
    "Chief Operating Officer": "VP of Operations",
    "Chief Revenue Officer": "Sales Lead",
    "VP of Sales": "Sales Lead",
    "VP of Engineering": "Engineering Lead",
    "VP of Product": "Head of Product",
    "VP of Finance": "Finance Lead",
    "CFO": "Finance Lead",
    "CTO": "Engineering Lead",
    "CISO": "Security Lead",
    "COO": "VP of Operations",
    "CRO": "Sales Lead",
}
# longest-first so "Chief Financial Officer" matches before any short form
_ALIAS_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in
                      sorted(ROLE_ALIASES, key=len, reverse=True)) + r")\b")

# role-ish terms with no clean 1:1 mapping (the org has no HR or Marketing
# function) — flagged for the Tier-2 judge to reword from context.
_UNMAPPED_RE = re.compile(
    r"\b(HR|Human Resources|Marketing team|Marketing department|"
    r"Procurement team|the board of directors)\b", re.IGNORECASE)
_ARTIFACT_REF_RE = re.compile(
    r"\bevent_\d{3}__m\d+_a\d+_[a-z]+\b"
    r"|\bevent_\d{3}__m\d+_[a-z]+\b"
)
_DATE_SEP = r"[-\u2010\u2011\u2012\u2013\u2014\u2212]"
_ISO_RE = re.compile(rf"\b\d{{4}}{_DATE_SEP}\d{{2}}{_DATE_SEP}\d{{2}}\b")
_PAST_OK = re.compile(
    r"\b(was due|overdue|already|completed|uploaded|posted|recorded|"
    r"executed|deployed|previously|historical|on \d{4})\b",
    re.IGNORECASE,
)
_PAST_DEADLINE_BEFORE = re.compile(
    r"(?:\b(?:due|due by|by|target|targeted|deadline)\b"
    r"|\bwill\s+(?:complete|upload|send|review|provide|finali[sz]e|"
    r"deliver|share|file|submit)\s+by\b)"
    r"\s*:?\s*(?:[*_`]*\s*)$",
    re.IGNORECASE,
)
_FUTURE_COMPLETED_BEFORE = re.compile(
    r"\b(?:completed|uploaded|posted|recorded|approved|deployed|executed|"
    r"signed off|went live|is live|are live)\s+(?:on|as of)\s*$",
    re.IGNORECASE,
)


def _norm_date_token(s: str) -> str:
    return re.sub(_DATE_SEP, "-", s.strip())


def _parse_isoish(s: str):
    from datetime import date
    try:
        return date.fromisoformat(_norm_date_token(s))
    except ValueError:
        return None


def _pathlike_date(text: str, start: int, end: int) -> bool:
    """True when an ISO-like date is part of a path/id rather than prose."""
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    path_chars = set("/\\_:")
    if before in path_chars or after in path_chars:
        return True
    if before.isalnum() or after.isalnum():
        return True
    return False


def check_roster(event: Event) -> list[ValidationIssue]:
    """Scrub invented role titles in item text; flag unmapped role terms."""
    issues: list[ValidationIssue] = []
    fixed = 0
    flagged: set[str] = set()

    for art in event.artifacts:
        for item in art.items:
            def _sub(m: re.Match) -> str:
                nonlocal fixed
                fixed += 1
                return ROLE_ALIASES[m.group(0)]
            item.text = _ALIAS_RE.sub(_sub, item.text)
            for m in _UNMAPPED_RE.finditer(item.text):
                flagged.add(m.group(0))

    if fixed:
        issues.append(ValidationIssue(
            check="roster_role_alias", tier="rule", severity="realism",
            detail=f"scrubbed {fixed} invented role title(s) to the roster",
            resolved=True))
    if flagged:
        issues.append(ValidationIssue(
            check="roster_unmapped_role", tier="rule", severity="realism",
            detail=("non-roster role term(s) need contextual rewording: "
                    + ", ".join(sorted(flagged))),
            resolved=False))
    return issues


def check_actor_ids(event: Event, org: Organization) -> list[ValidationIssue]:
    """Guard against portfolio/org drift: every emp_id referenced by the
    event must resolve to a real employee in the current organisation.

    Ghost emp_ids (frozen in the portfolio at an earlier org version,
    then orphaned when the org was regenerated) silently corrupt the
    rendered surface: the LLM is handed a literal id string like
    ``E_carol`` and invents a plausible full name to render with it, so
    the same fictional person appears across an event's artifacts but
    is unmapped at evaluation time.

    Scope: ``frame.candidate_actors``, ``scenario.actors_used``,
    ``scenario.milestones[*].actors``, every artifact's metadata audience
    fields (recipients/attendees/sharing_list/channel_members), and the
    item ``sender`` field. Any unknown emp_id is a broken severity issue.
    """
    real = {e.emp_id for e in org.employees}
    ghosts: set[str] = set()

    def _collect(emps):
        for e in (emps or []):
            if isinstance(e, str) and e.startswith("E_") and e not in real:
                ghosts.add(e)

    if event.frame:
        _collect(event.frame.candidate_actors)
    if event.scenario:
        _collect(event.scenario.actors_used)
        for ms in event.scenario.milestones:
            _collect(ms.actors)
        for af in event.scenario.authority_failures:
            if af.expected and af.expected not in real:
                ghosts.add(af.expected)
    for art in event.artifacts:
        md = art.metadata
        _collect(md.channel_members)
        _collect(md.attendees)
        _collect(md.sharing_list)
        if md.recipients:
            for k in ("to", "cc", "bcc"):
                _collect(md.recipients.get(k))
        f = art.form
        _collect(f.prepared_by)
        _collect(f.reviewed_by)
        if f.assignee:
            _collect([f.assignee])
        if f.approver:
            _collect([f.approver])
        _collect(art.absent_actors)
        for it in art.items:
            if it.sender:
                _collect([it.sender])

    if ghosts:
        return [ValidationIssue(
            check="ghost_actor_id", tier="rule", severity="broken",
            detail=("event references emp_id(s) not in the organisation: "
                    + ", ".join(sorted(ghosts))
                    + " — portfolio/org drift; rendered text may reference "
                    "invented people"),
            resolved=False)]
    return []


def check_meeting_feasibility(event: Event) -> list[ValidationIssue]:
    """Meeting structural invariant — flag impossible meetings.

    The 2026-05-24 deep audit found three classes of impossible meeting:
      - all attendees absent (event_028, event_068),
      - one-person meeting where the sole invitee is absent (event_054),
      - one-person meeting at all (the artifact is naturally a memo).

    The planner now enforces ≥ 2 invitees and the scheduler restores
    presence so ≥ 1 (≥ 2 when invitees ≥ 2) is present. This check is the
    belt-and-braces guard at Step 4: if anything regresses, we want a hard
    failure rather than a silently corrupt artifact.
    """
    issues: list[ValidationIssue] = []
    for art in event.artifacts:
        if art.channel_type != "meeting":
            continue
        invited = list(art.metadata.attendees or [])
        absent = list(art.absent_actors or [])
        present = [a for a in invited if a not in absent]
        if len(invited) < 2:
            issues.append(ValidationIssue(
                check="meeting_too_small", tier="rule", severity="broken",
                detail=(f"meeting has < 2 invitees ({len(invited)}); "
                        "downgrade to email at plan time"),
                locus=art.artifact_id))
            continue
        if not present:
            issues.append(ValidationIssue(
                check="meeting_all_absent", tier="rule", severity="broken",
                detail=("every meeting invitee is marked absent; "
                        "the meeting cannot have happened as written"),
                locus=art.artifact_id))
        elif len(present) < 2 and len(invited) >= 2:
            issues.append(ValidationIssue(
                check="meeting_solo_present", tier="rule", severity="realism",
                detail=(f"only one of {len(invited)} invitees is present; "
                        "discussion narratives are unrealistic for a 1:0 meeting"),
                locus=art.artifact_id))
    return issues


def check_form_metadata_consistency(event: Event) -> list[ValidationIssue]:
    """Surface form-header / metadata audience misalignment.

    Each artifact's `form.reviewed_by` represents people who actively
    reviewed the artifact; `metadata.sharing_list` (document) or
    `metadata.recipients.to/cc/bcc` (email/approval) represent who has
    read access. The two should align (everyone who reviewed it had
    access, and any active reviewer ought to be on the shared list).

    The previous renderer's `_sync_form_metadata` synced sharing_list
    from reviewed_by but never the reverse, so it was possible for a
    name to land in `form.reviewed_by` without being in
    `metadata.sharing_list` — the reviewer LLM flagged that pattern as
    an authority_cue inconsistency. This validator surfaces the
    mismatch without forcing a correction (auto-syncing the two would
    blur the distinct semantics of "reviewer" vs "shared with").
    """
    issues: list[ValidationIssue] = []
    for art in event.artifacts:
        f = art.form
        md = art.metadata
        if art.channel_type == "document":
            shared = set(md.sharing_list or [])
            reviewed = set(f.reviewed_by or [])
            missing = reviewed - shared - set(f.prepared_by or [])
            if missing:
                issues.append(ValidationIssue(
                    check="form_metadata_audience_mismatch",
                    tier="rule", severity="realism",
                    detail=(
                        f"form.reviewed_by includes {sorted(missing)} but "
                        "metadata.sharing_list does not — reader of the "
                        "document header would not be on the shared list"),
                    locus=art.artifact_id,
                    resolved=False))
        elif art.channel_type == "approval":
            rcpt = md.recipients or {}
            recipients = set((rcpt.get("to") or [])
                             + (rcpt.get("cc") or [])
                             + (rcpt.get("bcc") or []))
            approver = f.approver
            if approver and approver not in recipients:
                issues.append(ValidationIssue(
                    check="form_metadata_audience_mismatch",
                    tier="rule", severity="realism",
                    detail=(
                        f"form.approver={approver} is not on the approval "
                        "record's recipient list"),
                    locus=art.artifact_id,
                    resolved=False))
    return issues


def check_af4_surface(event: Event, org: Organization) -> list[ValidationIssue]:
    """For each AF4 origin artifact, verify the wrong-vs-right reviewer
    pair is recoverable on the surface — both the actual approver of
    record AND the authorised reviewer must appear by full name in the
    artifact body.

    AF4's whole evaluative purpose is the wrong/right contrast; if only
    one name shows up the body doesn't realise the failure, even if
    `form.approver` and `af.expected` are correctly set. Surface as a
    broken validation issue so it gets surfaced in the report (we
    don't auto-correct — the body needs regeneration or manual edit).
    """
    if not event.scenario:
        return []
    issues: list[ValidationIssue] = []
    name = {e.emp_id: e.name for e in org.employees}

    def _norm_text(s: str) -> str:
        # LLM output often uses narrow no-break spaces inside names
        # ("Aarav Tanaka"). Normalize every Unicode separator to a plain
        # space before checking full-name surface recoverability.
        s = unicodedata.normalize("NFKC", s or "")
        return re.sub(r"\s+", " ", s)

    for af in event.scenario.authority_failures or []:
        if af.af_code != "AF4" or not af.expected or not af.origin:
            continue
        art = next((a for a in event.artifacts
                    if a.artifact_id == af.origin), None)
        if not art:
            continue
        body = _norm_text("\n".join(it.text for it in art.items))
        expected_name = _norm_text(name.get(af.expected, ""))
        actual_id = art.form.approver if art.form else ""
        actual_name = _norm_text(name.get(actual_id, ""))
        missing: list[str] = []
        if expected_name and expected_name not in body:
            missing.append(f"authorised reviewer {expected_name}")
        if actual_name and actual_name not in body:
            missing.append(f"approver of record {actual_name}")
        if missing:
            issues.append(ValidationIssue(
                check="af4_surface_missing", tier="rule", severity="broken",
                detail=(
                    "AF4 wrong-reviewer surface incomplete — body of "
                    f"{art.artifact_id} does not name: "
                    + "; ".join(missing)),
                locus=art.artifact_id, resolved=False))
    return issues


def check_artifact_references(event: Event) -> list[ValidationIssue]:
    """Flag hallucinated internal artifact references.

    The renderer sometimes emits bracketed references such as
    ``[event_061__m4_document]``. These look authoritative to a reader, so a
    non-existent reference should be visible in Step 4. This check is flag-only:
    it never rewrites body text.
    """
    known = {a.artifact_id for a in event.artifacts}
    issues: list[ValidationIssue] = []
    for art in event.artifacts:
        for item in art.items:
            bad = sorted({m.group(0) for m in _ARTIFACT_REF_RE.finditer(item.text)
                          if m.group(0) not in known})
            if bad:
                issues.append(ValidationIssue(
                    check="bad_artifact_ref", tier="rule",
                    severity="realism",
                    detail=("non-existent artifact reference(s): "
                            + ", ".join(bad)),
                    locus=item.item_id,
                    resolved=False))
    return issues


def check_temporal_surface(event: Event) -> list[ValidationIssue]:
    """Flag high-confidence temporal stance contradictions.

    This is deliberately conservative and flag-only. The render gate may
    rewrite narrow "due/by/target DATE" past-deadline patterns, but this
    validator reports broader cases that require regeneration or manual
    judgement, such as future dates described as already completed.
    """
    issues: list[ValidationIssue] = []
    for art in event.artifacts:
        for item in art.items:
            item_day = _parse_isoish(item.date or "")
            if not item_day:
                continue
            text = item.text or ""
            for m in _ISO_RE.finditer(text):
                if _pathlike_date(text, m.start(), m.end()):
                    continue
                d = _parse_isoish(m.group(0))
                if not d:
                    continue
                before = text[max(0, m.start() - 80):m.start()]
                # Flag only high-confidence deadline/action phrases where the
                # date itself is syntactically attached to "due/by/target".
                # Broad windows produced too many false positives on historical
                # references, paths, and legitimate future milestone mentions.
                if (d < item_day
                        and _PAST_DEADLINE_BEFORE.search(before)
                        and not _PAST_OK.search(before)):
                    issues.append(ValidationIssue(
                        check="temporal_surface", tier="rule",
                        severity="realism",
                        detail=(f"past date {m.group(0)} appears in a "
                                f"deadline/action context in item dated "
                                f"{item.date}"),
                        locus=item.item_id,
                        resolved=False))
                    break
                if d > item_day and _FUTURE_COMPLETED_BEFORE.search(before):
                    issues.append(ValidationIssue(
                        check="temporal_surface", tier="rule",
                        severity="realism",
                        detail=(f"future date {m.group(0)} appears in a "
                                f"completed-fact context in item dated "
                                f"{item.date}"),
                        locus=item.item_id,
                        resolved=False))
                    break
    return issues


def check_surface_gates(event: Event, org: Organization) -> list[ValidationIssue]:
    """Apply the deterministic render gates to every item; mutates in place.

    The renderer applies these gates per-item in Step 3. This Step 4 sweep
    is the belt-and-braces guard that catches anything the renderer
    skipped (e.g. an item rendered before the gates were wired in, or
    text edited by the Tier-2 judge after the gate ran). It uses the
    same gate code path, so behaviour is identical.

    Issues bubble up as ValidationIssues at ``realism`` severity — these
    are surface polish, not label-fidelity breaks. The gate output text
    is written back to ``item.text``.
    """
    from .render_gates import run_all_gates

    name = {e.emp_id: e.name for e in org.employees}
    roster_full = set(name.values())
    roster_first = {n.split()[0] for n in roster_full if n}
    issues: list[ValidationIssue] = []
    for art in event.artifacts:
        # build local-participant set for this artifact
        md = art.metadata
        f = art.form
        ch = art.channel_type
        if ch == "chat":
            local_ids = list(md.channel_members or [])
        elif ch == "email":
            rcpt = md.recipients or {}
            local_ids = list((rcpt.get("to") or []) + (rcpt.get("cc") or [])
                             + (rcpt.get("bcc") or []))
        elif ch == "meeting":
            local_ids = [a for a in (md.attendees or [])
                         if a not in (art.absent_actors or [])]
        elif ch == "document":
            local_ids = list(dict.fromkeys(
                (md.sharing_list or []) + (f.prepared_by or [])
                + (f.reviewed_by or [])))
        elif ch == "approval":
            rcpt = md.recipients or {}
            local_ids = list(dict.fromkeys(
                (rcpt.get("to") or []) + (rcpt.get("cc") or [])
                + (rcpt.get("bcc") or [])
                + ([f.approver] if f.approver else [])))
        else:
            local_ids = list(event.frame.candidate_actors or []) if event.frame else []
        local_full = {name.get(i, i) for i in local_ids if name.get(i)}
        local_first = {n.split()[0] for n in local_full if n}
        # exempt drift targets from direct-address gate
        exempt = set()
        if event.frame:
            for d in event.frame.drift_events or []:
                for u in d.target_users or []:
                    nm = name.get(u)
                    if nm:
                        exempt.add(nm)
        item_count = 0
        for it in art.items:
            iso = it.date or None
            cleaned, gate_issues = run_all_gates(
                it.text or "",
                channel_type=ch, artifact_iso=iso,
                local_full_names=local_full, local_first_names=local_first,
                roster_full_names=roster_full, roster_first_names=roster_first,
                exempt_names=exempt,
            )
            if gate_issues:
                item_count += 1
                if cleaned != it.text:
                    it.text = cleaned
                # collate one issue per gate finding
                for g in gate_issues:
                    issues.append(ValidationIssue(
                        check="render_gate", tier="rule",
                        severity="realism",
                        detail=g[:300], locus=it.item_id, resolved=True))
        # No need for an artifact-level summary issue; per-item issues
        # already carry locus.
    return issues


def validate_structure(event: Event) -> list[ValidationIssue]:
    """Cheap structural / label-surface checks decidable without an LLM."""
    issues: list[ValidationIssue] = []

    if not event.artifacts:
        return [ValidationIssue(
            check="no_artifacts", tier="rule", severity="broken",
            detail="event has no artifacts")]

    for art in event.artifacts:
        empties = sum(1 for it in art.items if not it.text.strip())
        if empties:
            issues.append(ValidationIssue(
                check="empty_item", tier="rule", severity="broken",
                detail=f"{empties} item(s) with empty text",
                locus=art.artifact_id))

    # the committed AF set must equal the scenario's authority_failures
    if event.frame and event.scenario:
        committed = sorted(event.frame.af_codes)
        got = sorted(a.af_code for a in event.scenario.authority_failures)
        if committed != got:
            issues.append(ValidationIssue(
                check="af_code_mismatch", tier="rule", severity="broken",
                detail=f"frame af_codes {committed} != scenario {got}"))
        # one drift event per committed AF5
        n_af5 = event.frame.af_codes.count("AF5")
        if len(event.frame.drift_events) != n_af5:
            issues.append(ValidationIssue(
                check="drift_count_mismatch", tier="rule", severity="broken",
                detail=(f"{len(event.frame.drift_events)} drift event(s) "
                        f"for {n_af5} committed AF5")))

    return issues
