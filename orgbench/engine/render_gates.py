"""Deterministic post-render gates — surface validators for rendered items.

The 2026-05-24 eval-grade audit identified six classes of defect the LLM
renderer produces despite prompt-level guardrails. These are systemic
enough that prompts alone cannot eliminate them, but every one is purely
syntactic — solvable by deterministic rewrite or rejection. This module
implements those gates as pure functions over a single item's text.

Gates implemented:

  - :func:`gate_calendar`          weekday/date pair consistency
  - :func:`gate_temporal_actions`  action-item dates ≥ artifact date
  - :func:`gate_direct_address`    direct-address only to local participants
  - :func:`gate_paths`             POSIX paths only (Windows UNC corruption)
  - :func:`gate_name_stutter`      "Jam Jamal" prefix stutter cleanup
  - :func:`gate_chat_length`       chat-register length cap (advisory)

Each gate returns a tuple ``(cleaned_text, issues)`` where ``issues`` is
a (possibly empty) list of short human-readable problem strings. Callers
that want the cleaned text just keep [0]; callers that want a structural
report keep [1] and emit ValidationIssues.

The gates are designed so a clean input is a no-op: calling them on text
the LLM produced correctly returns ``(text, [])`` unchanged. So they are
safe to wire into the renderer's per-item cleanup path even before the
upstream prompts have been improved.
"""

from __future__ import annotations

import re
from datetime import date as _date

__all__ = [
    "gate_calendar", "gate_temporal_actions", "gate_direct_address",
    "gate_paths", "gate_name_stutter", "gate_chat_length",
    "gate_zero_width",
    "normalize_date_token",
    "run_all_gates",
]


# ---------------------------------------------------------------------------
# Zero-width / control character scrub
# ---------------------------------------------------------------------------

_ZW_CHARS = {
    "​": "", "‌": "", "‍": "", "⁠": "",
    "﻿": "",
    "‎": "", "‏": "",        # LTR/RTL marks
    "⁡": "", "⁢": "", "⁣": "", "⁤": "",  # math invisibles
    "­": "",                       # soft hyphen
}
_ZW_RUN = re.compile(r"(\s)\1{4,}")     # repeated whitespace runs > 4
_DASH_RUN = re.compile(r"(?:[-–—]\s*){3,}")   # "--- --- ---" boilerplate
_TOK_REPEAT = re.compile(r"\b(\w+)(?:\s+\1\b){2,}", re.IGNORECASE)
_ZW_RE = re.compile("|".join(map(re.escape, _ZW_CHARS)))
_PLACEHOLDER_LINE = re.compile(
    r"(?im)^[^\n]*(?:\?[\s\u00a0\u202f]*){3,}[^\n]*(?:…|\.\.\.)?[^\n]*$"
    r"|^\s*(?:[-*]|\d+\.)\s*(?:…|\.\.\.)\s*$"
)


def gate_zero_width(text: str) -> tuple[str, list[str]]:
    """Strip zero-width chars and collapse pathological whitespace / repeat
    patterns that look like model glitch loops.

    Defects observed:
      - "Review review-d​​​     review review" (zero-width joiners + repeat)
      - "NovaNova ​    ​          ​ ---   ​  --- " (garbled vendor name)
    Both look like the model entering a repetition loop and emitting
    invisible chars to pad it.
    """
    issues = []
    out = text

    if any(ch in out for ch in _ZW_CHARS):
        n = sum(out.count(ch) for ch in _ZW_CHARS)
        out = _ZW_RE.sub("", out)
        issues.append(f"stripped {n} zero-width character(s)")

    new = _ZW_RUN.sub(r"\1", out)
    if new != out:
        issues.append("collapsed pathological whitespace runs")
        out = new

    new = _DASH_RUN.sub("— ", out)
    if new != out:
        issues.append("collapsed repeated-dash glitch")
        out = new

    new = _TOK_REPEAT.sub(r"\1", out)
    if new != out:
        issues.append("collapsed repeated-token glitch")
        out = new

    new = _PLACEHOLDER_LINE.sub("", out)
    if new != out:
        issues.append("removed malformed placeholder line(s)")
        out = re.sub(r"\n{3,}", "\n\n", new).strip()

    return out, issues


# ---------------------------------------------------------------------------
# Calendar weekday/date consistency
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}
_WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}
_WD_NAMES = {v: ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[v]
             for v in range(7)}
_MONTH_RE = r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|" \
            r"Jun|June|Jul|July|Aug|August|Sep|Sept|September|" \
            r"Oct|October|Nov|November|Dec|December)"
_WD_RE = r"(?:Mon|Mond|Monday|Tue|Tues|Tuesday|Wed|Wedn|Wednesday|" \
         r"Thu|Thur|Thurs|Thursday|Fri|Friday|Sat|Saturday|Sun|Sunday)"
_DATE_SEP = r"[-\u2010\u2011\u2012\u2013\u2014\u2212]"
_ISO_TOKEN = rf"\d{{4}}{_DATE_SEP}\d{{2}}{_DATE_SEP}\d{{2}}"

# Pattern A: "Wednesday May 29" or "Wednesday May 29, 2026"
_CAL_A = re.compile(
    rf"\b(?P<wd>{_WD_RE})\s+(?P<mo>{_MONTH_RE})\.?\s+(?P<dy>\d{{1,2}})"
    rf"(?:,?\s+(?P<yr>\d{{4}}))?\b",
    re.IGNORECASE)
# Pattern B: "Tuesday 14 Nov" / "Friday 05 Nov, 2026"
_CAL_B = re.compile(
    rf"\b(?P<wd>{_WD_RE})\s+(?P<dy>\d{{1,2}})\s+(?P<mo>{_MONTH_RE})\.?"
    rf"(?:,?\s+(?P<yr>\d{{4}}))?\b",
    re.IGNORECASE)
# Pattern C: "Wednesday, 2026-05-29"
_CAL_C = re.compile(
    rf"\b(?P<wd>{_WD_RE}),?\s+(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})\b",
    re.IGNORECASE)


def _infer_year(base_iso: str | None) -> int | None:
    if base_iso:
        try:
            return _date.fromisoformat(base_iso).year
        except ValueError:
            return None
    return None


def normalize_date_token(s: str) -> str:
    """Normalize Unicode date separators inside an ISO-like date token.

    The renderer often emits non-breaking hyphens (``2026‑03‑07``). Python's
    ``date.fromisoformat`` only accepts ASCII ``-``; normalizing only the
    token lets validators detect dates without rewriting general prose.
    """
    return re.sub(_DATE_SEP, "-", s.strip())


def gate_calendar(
    text: str, *, base_iso: str | None = None,
) -> tuple[str, list[str]]:
    """Reject weekday/date pairs that disagree.

    When the LLM writes "Wednesday May 29" the weekday is often a
    fabrication — the real May 29 2026 is a Friday. We drop the weekday
    word (the date carries the truth) and log the issue. This is safer
    than re-deriving "Friday May 29" because the rest of the sentence may
    already reference the weekday separately.
    """
    issues: list[str] = []
    inferred_year = _infer_year(base_iso)

    def _fix(m: re.Match, *, month_idx: int, day_idx: int,
             year_idx: int | None) -> str:
        wd_word = m.group("wd")
        mo_word = m.group("mo").lower().rstrip(".")
        try:
            day = int(m.group("dy"))
        except (TypeError, ValueError):
            return m.group(0)
        year_raw = m.group("yr") if year_idx is not None else None
        year = int(year_raw) if year_raw else inferred_year
        if year is None:
            return m.group(0)
        mo = _MONTHS.get(mo_word)
        if not mo:
            return m.group(0)
        try:
            d = _date(year, mo, day)
        except ValueError:
            return m.group(0)
        wd_actual = d.weekday()
        wd_claimed = _WEEKDAYS.get(wd_word.lower())
        if wd_claimed is None or wd_claimed == wd_actual:
            return m.group(0)
        # Mismatch — drop the weekday word; the rest of the date is fine.
        issues.append(
            f"weekday/date mismatch: '{m.group(0)}' (actual: "
            f"{_WD_NAMES[wd_actual]} {year}-{mo:02d}-{day:02d})")
        # rebuild the phrase minus the weekday
        return m.group(0)[len(wd_word):].lstrip(" ,")

    out = _CAL_A.sub(lambda m: _fix(m, month_idx=2, day_idx=3, year_idx=4), text)
    out = _CAL_B.sub(lambda m: _fix(m, month_idx=3, day_idx=2, year_idx=4), out)

    def _fix_iso(m: re.Match) -> str:
        try:
            d = _date.fromisoformat(m.group("iso"))
        except ValueError:
            return m.group(0)
        wd_word = m.group("wd")
        wd_actual = d.weekday()
        wd_claimed = _WEEKDAYS.get(wd_word.lower())
        if wd_claimed is None or wd_claimed == wd_actual:
            return m.group(0)
        issues.append(
            f"weekday/date mismatch: '{m.group(0)}' (actual: "
            f"{_WD_NAMES[wd_actual]} {m.group('iso')})")
        return m.group("iso")
    out = _CAL_C.sub(_fix_iso, out)
    return out, issues


# ---------------------------------------------------------------------------
# Temporal action-item gate
# ---------------------------------------------------------------------------

# canonical action contexts that signal a future commitment
_ACTION_CONTEXT = re.compile(
    r"(?i)(?:^|[\s\-•])"
    r"(due|due by|by|target|targeted|deadline|"
    r"will (?:complete by|upload by|send by|review by))"
    r"\s*:?\s*(?:[*_`]*\s*)"
    rf"(?P<date>{_ISO_TOKEN}"
    rf"|{_MONTH_RE}\.?\s+\d{{1,2}}(?:,?\s+\d{{4}})?"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\.?(?:,?\s+\d{4})?"
    r")(?:\s*[*_`]*)"
)

# anchors that mean "this past date is OK because we already know it's past"
_PAST_OK = re.compile(
    r"(?i)\b(completed|was due|overdue|already (?:done|completed|delivered)|"
    r"originally\s+(?:due|targeted|scheduled)|previously\s+(?:due|targeted|"
    r"scheduled)|past\s+due)\b")


def _parse_loose_date(s: str, fallback_year: int | None) -> _date | None:
    s = normalize_date_token(s.strip().rstrip(".,"))
    # ISO
    try:
        return _date.fromisoformat(s)
    except ValueError:
        pass
    # Mar 5 / March 5 / Mar 5, 2026
    m = re.match(
        rf"^({_MONTH_RE})\.?\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?$",
        s, re.IGNORECASE)
    if m:
        mo = _MONTHS.get(m.group(1).lower().rstrip("."))
        day = int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else fallback_year
        if mo and yr:
            try:
                return _date(yr, mo, day)
            except ValueError:
                return None
    # 5 Mar / 5 Mar 2026
    m = re.match(
        rf"^(\d{{1,2}})\s+({_MONTH_RE})\.?(?:,?\s+(\d{{4}}))?$",
        s, re.IGNORECASE)
    if m:
        day = int(m.group(1))
        mo = _MONTHS.get(m.group(2).lower().rstrip("."))
        yr = int(m.group(3)) if m.group(3) else fallback_year
        if mo and yr:
            try:
                return _date(yr, mo, day)
            except ValueError:
                return None
    return None


def gate_temporal_actions(
    text: str, *, artifact_iso: str,
) -> tuple[str, list[str]]:
    """Reject/repair action-item dates earlier than the artifact's own date.

    Example defect (event_063, meeting dated 2026-02-25)::

        - Compile a summarized document of the five selected use-cases —
          owner: Julia Kim; due: 2026-02-20

    The text presents 2026-02-20 as a future deadline, but the meeting
    happened on 2026-02-25. We rewrite ``due: 2026-02-20`` to
    ``(was due 2026-02-20)`` so the artifact is internally consistent —
    the reader sees the past deadline marked as past rather than
    promising it forward.
    """
    issues: list[str] = []
    try:
        base = _date.fromisoformat(artifact_iso)
    except (TypeError, ValueError):
        return text, []

    # Process line-by-line so the past-OK anchor lookup stays local. Keep the
    # repair deliberately narrow: only deadline-style "due/by/target DATE"
    # phrases get rewritten. Completed facts, kickoff dates, deployment dates,
    # and other event-history statements are reported by Step 4 if suspicious, but
    # are not deterministically rephrased here.
    lines = text.split("\n")
    out_lines: list[str] = []
    for line in lines:
        # quick reject — line already explicitly marked as past
        already_past = bool(_PAST_OK.search(line))

        def _repair(m: re.Match) -> str:
            raw = m.group(0)
            verb = m.group(1)
            date_str = m.group("date")
            d = _parse_loose_date(date_str, base.year)
            if d is None or d >= base:
                return raw
            if already_past:
                return raw
            issues.append(
                f"past-date action: '{raw.strip()}' on artifact "
                f"dated {artifact_iso}")
            # Rewrite: replace "due: X" / "by X" / "target X" with
            # "(was due X)" so the future-tense framing flips to past.
            # Preserve any leading whitespace/bullet so list rendering stays.
            leader = raw[: raw.lower().find(verb.lower())]
            return f"{leader}(was due {date_str})"

        out_lines.append(_ACTION_CONTEXT.sub(_repair, line))
    return "\n".join(out_lines), issues


# ---------------------------------------------------------------------------
# Nonlocal direct-address gate
# ---------------------------------------------------------------------------

# "Name - please ..." / "Name, please ..." / "Name: ..."
# A direct-address pattern: an initial-caps first-name (single token) or
# full name, followed by an imperative-cue punctuation (dash/comma/colon),
# then an imperative verb or a content-bearing clause.
_ADDRESS_PUNCT = r"\s*[-—–,:]\s+"
_IMPERATIVE_LEAD = (
    r"(?:please|could you|can you|kindly|would you|"
    r"let(?:'s)?|circulate|confirm|review|share|"
    r"send|prepare|submit|file|sign|approve|"
    r"finalize|finalise|sign-?off|close|update|"
    r"coordinate|ensure|provide|outline|drive|"
    r"once|after|when|before)"
)
_ADDRESS_RE = re.compile(
    rf"(?P<lead>(?:^|[\n\.\!]\s+|^\s*-\s+))"
    rf"(?P<name>(?:[A-Z][a-z]+(?:,?\s+(?:and\s+)?[A-Z][a-z]+){{0,3}}))"
    rf"{_ADDRESS_PUNCT}(?P<verb>{_IMPERATIVE_LEAD})",
    re.MULTILINE | re.IGNORECASE)

# Secondary: sentence-initial "Name —" or "Name -" followed by a clause of
# ≥ 5 lowercase words. Catches direct-address patterns where the clause is
# a statement to the addressee (event_017: "Felix – the data-residency
# compliance clause stays confidential ...") rather than an imperative.
# We require em-dash / en-dash / double-hyphen separator (not just comma)
# to avoid catching appositives like "Felix, the engineering lead, reviewed".
_ADDRESS_DASH_RE = re.compile(
    r"(?P<lead>(?:^|[\n\.\!\?]\s+))"
    r"(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
    r"\s+[—–-]{1,2}\s+"
    r"(?P<rest>(?:\w+\W+){4,}\w+)",
    re.MULTILINE)


def _split_address_names(raw: str) -> list[str]:
    """Split 'Aarav, Bob, and Ivan' into ['Aarav', 'Bob', 'Ivan'].
    Also handles single 'Felix' or two-token 'Yara Stein'."""
    s = raw.replace(" and ", ", ")
    return [t.strip() for t in s.split(",") if t.strip()]


def gate_direct_address(
    text: str, *,
    local_full_names: set[str],
    local_first_names: set[str],
    roster_full_names: set[str],
    roster_first_names: set[str],
    exempt_names: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Replace direct address to roster persons outside the local boundary.

    The audit's most-damaging defect class: a chat with
    ``channel_members = [E_jamal, E_felix]`` containing the line
    ``"Aarav, Bob, and Ivan — please provide an initial legal risk
    assessment."`` makes Aarav/Bob/Ivan look like channel members. The
    fix replaces the imperative-address form with a generic role-style
    reference, so the surface no longer puts non-members in the room.

    ``exempt_names`` covers committed AF/drift targets — those names are
    intentionally introduced by the engine and should not be scrubbed.
    """
    exempt = set(exempt_names or ())
    issues: list[str] = []

    def _repl(m: re.Match) -> str:
        names_blob = m.group("name")
        verb = m.group("verb")
        lead = m.group("lead")
        # tokenise the address blob
        names = _split_address_names(names_blob)
        local_count = 0
        offending: list[str] = []
        for nm in names:
            if nm in exempt:
                continue
            if (nm in local_full_names or nm in local_first_names
                    or any(nm == fn.split()[0] for fn in local_full_names)):
                local_count += 1
                continue
            # is it a real roster person at all?
            if (nm in roster_full_names or nm in roster_first_names
                    or any(nm == fn.split()[0] for fn in roster_full_names)):
                offending.append(nm)
        if not offending:
            return m.group(0)
        # If at least one local is also addressed, keep the locals and
        # drop the offenders; otherwise replace the whole address with
        # "The relevant colleagues — please …" generic.
        if local_count > 0:
            kept = [nm for nm in names if nm not in offending]
            issues.append(
                f"dropped nonlocal direct address: {', '.join(offending)}")
            return f"{lead}{', '.join(kept)} — {verb}"
        issues.append(
            f"replaced nonlocal direct address: {', '.join(offending)}")
        return f"{lead}The relevant colleague — {verb}"

    out = _ADDRESS_RE.sub(_repl, text)

    def _repl_dash(m: re.Match) -> str:
        names = _split_address_names(m.group("name"))
        local_count = 0
        offending: list[str] = []
        for nm in names:
            if nm in exempt:
                continue
            first = nm.split()[0]
            if (nm in local_full_names or nm in local_first_names
                    or first in local_first_names
                    or any(nm == fn.split()[0] for fn in local_full_names)):
                local_count += 1
                continue
            if (nm in roster_full_names or nm in roster_first_names
                    or first in roster_first_names
                    or any(nm == fn.split()[0] for fn in roster_full_names)):
                offending.append(nm)
        if not offending:
            return m.group(0)
        lead = m.group("lead")
        rest = m.group("rest")
        if local_count > 0:
            kept = [nm for nm in names if nm not in offending]
            issues.append(
                f"dropped nonlocal direct address: {', '.join(offending)}")
            return f"{lead}{', '.join(kept)} — {rest}"
        issues.append(
            f"replaced nonlocal direct address: {', '.join(offending)}")
        return f"{lead}The relevant colleague — {rest}"

    out = _ADDRESS_DASH_RE.sub(_repl_dash, out)
    return out, issues


# ---------------------------------------------------------------------------
# Path normalizer — Windows UNC / backslash paths → POSIX
# ---------------------------------------------------------------------------

# Match a backslash-prefixed path token. We treat any \\... or \... sequence
# followed by at least one path-ish segment as suspect.
_PATH_RE = re.compile(
    r"`?\\{1,2}[A-Za-z0-9_\-\. ]+(?:\\{1,2}[A-Za-z0-9_\-\.\s]+){1,}\.?[A-Za-z0-9]*`?"
)
# inside a path: a leading space-then-letter often indicates \t / \r / \n
# escape corruption (e.g. "\\team" → " eam" because JSON parsed \t as TAB).
_CORRUPT_SEG = re.compile(r"\s+([a-z][a-zA-Z0-9_\-]+)")


def gate_paths(text: str) -> tuple[str, list[str]]:
    """Convert Windows-style backslash paths to POSIX and repair escape
    corruption.

    Defect (event_068): ``\\shared eam esidency-dashboard\\baseline...``.
    Cause: the LLM emitted ``\\shared\team\residency-dashboard\\...``;
    when JSON-parsed, ``\t`` became a literal tab and ``\r`` a literal
    carriage return, eating the leading letter. We cannot recover the
    eaten letter, but we can:

      - convert ``\\`` to ``/`` so the path is at least well-formed,
      - reattach a plausible separator where the corruption left a gap.

    The corpus does not need to commit to any real filesystem layout, so
    a normalised POSIX path is strictly better than a broken UNC path.
    """
    issues: list[str] = []

    def _repl(m: re.Match) -> str:
        raw = m.group(0).strip("`")
        # convert backslashes to forward slashes
        repaired = raw.replace("\\", "/")
        # collapse runs of whitespace inside path segments (from \t/\r/\n)
        repaired = _CORRUPT_SEG.sub(r"/\1", repaired)
        repaired = re.sub(r"/{2,}", "/", repaired)
        repaired = re.sub(r"\s+", "", repaired)
        if repaired != raw:
            issues.append(f"normalised backslash path: '{raw}' → '{repaired}'")
        return repaired

    return _PATH_RE.sub(_repl, text), issues


# ---------------------------------------------------------------------------
# Name stutter cleanup — "Jam Jamal Osei" → "Jamal Osei"
# ---------------------------------------------------------------------------

_STUTTER_RE = re.compile(r"\b([A-Z][a-z]{1,6})\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def gate_name_stutter(
    text: str, *, roster_full_names: set[str],
) -> tuple[str, list[str]]:
    """Strip stutter prefixes where the suffix matches a roster full name.

    Defect (event_044): ``"Jam Jamal Osei"`` — the prefix ``Jam`` is a
    truncation artefact (likely a tokenisation seam in the LLM). We strip
    it when the trailing pair matches a known roster name and the prefix
    is a strict initial substring of the next token.
    """
    issues: list[str] = []

    def _repl(m: re.Match) -> str:
        prefix = m.group(1)
        tail = m.group(2)
        if tail not in roster_full_names:
            return m.group(0)
        first_of_tail = tail.split()[0]
        if not first_of_tail.lower().startswith(prefix.lower()):
            return m.group(0)
        issues.append(f"stripped name stutter prefix: '{prefix} {tail}' → '{tail}'")
        return tail

    return _STUTTER_RE.sub(_repl, text), issues


# ---------------------------------------------------------------------------
# Chat register / length advisory
# ---------------------------------------------------------------------------

_CHAT_DOC_MARKER = re.compile(r"^\s*##\s", re.MULTILINE)


def gate_chat_length(
    text: str, *, max_words: int = 250,
) -> tuple[str, list[str]]:
    """Advisory-only: flag chat items that look like memos.

    We do NOT truncate the text — silently dropping LLM output produces
    incoherent threads. Instead we emit an issue string so the harness
    can count how many chat items breach the register policy. The fix
    belongs in the renderer prompt (#36) — this gate measures whether
    the prompt fix worked.
    """
    issues: list[str] = []
    word_count = len(text.split())
    if word_count > max_words:
        issues.append(f"chat item too long: {word_count} words (cap {max_words})")
    if _CHAT_DOC_MARKER.search(text):
        issues.append("chat item contains markdown section heading")
    return text, issues


# ---------------------------------------------------------------------------
# Convenience: run every applicable gate on one item
# ---------------------------------------------------------------------------

def run_all_gates(
    text: str, *,
    channel_type: str,
    artifact_iso: str | None = None,
    local_full_names: set[str] | None = None,
    local_first_names: set[str] | None = None,
    roster_full_names: set[str] | None = None,
    roster_first_names: set[str] | None = None,
    exempt_names: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Run every applicable gate in the canonical order; collect issues.

    Order matters: paths first (so corrupt path tokens are normalised
    before the calendar regex tries to interpret embedded digits);
    calendar next (cheap); then temporal actions (which depend on
    calendar already being clean); then direct-address; then name
    stutter; then chat-length advisory.
    """
    out = text
    issues: list[str] = []

    out, more = gate_zero_width(out); issues += more
    out, more = gate_paths(out); issues += more
    out, more = gate_calendar(out, base_iso=artifact_iso); issues += more
    if artifact_iso:
        out, more = gate_temporal_actions(out, artifact_iso=artifact_iso)
        issues += more
    if (channel_type in ("chat", "email")
            and local_full_names is not None
            and roster_full_names is not None):
        out, more = gate_direct_address(
            out,
            local_full_names=local_full_names,
            local_first_names=local_first_names or set(),
            roster_full_names=roster_full_names,
            roster_first_names=roster_first_names or set(),
            exempt_names=exempt_names,
        )
        issues += more
    if roster_full_names is not None:
        out, more = gate_name_stutter(out, roster_full_names=roster_full_names)
        issues += more
    if channel_type == "chat":
        out, more = gate_chat_length(out)
        issues += more
    return out, issues
