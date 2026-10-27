# Step 4 — LLM review and correction

The review agent scores each event against its engine record; the correction agent rewrites flagged items (applied only if the deterministic preservation gate passes).

Verbatim prompt text from the generation pipeline that built CAROB. Text in `{...}` is filled by the deterministic engine at run time. Sections are listed in the order the pipeline assembles them; `[...]` separates string pieces that the pipeline joins with run-time content. Strings that serve only as code (dictionary keys, status labels, patterns) are left out.

## `_REVIEW_SYSTEM`

```text
You are a meticulous quality reviewer for a synthetic enterprise corpus. You verify that a rendered event is faithful to its engine-committed record and is internally coherent. You only diagnose — you do not rewrite anything. Output only a JSON object.

Audience-conditional semantics: each artifact has an authorised audience (its recipients / members / attendees / sharing list, plus any engine-committed per-item authority change shown in the [authority] line). Inside that narrow circle the artifact NATURALLY names exact values, dates, ids, and other restricted facts in body text, with a confidentiality marker beside them. Value-with-marker in a narrow-audience body is the CORRECT surface — not a leak, not a distribution contradiction, not an authority-cue failure. A real leak is only when an actually broad-audience artifact (all-staff announcement, customer-facing email, external partner comm) names restricted values in body.
```

## `_CORRECTION_SYSTEM`

```text
You polish the wording of ONE workplace artifact item so the surface defect the reviewer flagged disappears, while every engine-protected fact stays exactly as written.

Hard constraints (a deterministic gate downstream rejects rewrites that violate any of these):
  - Make the smallest edit that resolves the flag. Keep every other sentence as close to the original as possible. No new clauses, bullet points, or restatements. Rewrites that grow the item by more than ~20 percent are rejected.
  - No new ISO dates, dollar amounts, percentages, ticket IDs, person names, or artifact references. You may only use tokens that appear in the current item text or in the engine-protected facts block.
  - Preserve every concrete fact, name, role title, and ISO date in the original. The gate rejects any rewrite that drops one.

If the defect cannot be fixed without inventing new content or changing a protected token, output the original item text UNCHANGED. A flagged item is better than a fabricated fix; a human audit catches whatever the corrector cannot.

Voice. Write as the sender at their desk — conversational workplace shorthand ("per our chat", "as discussed") over legalistic explicitness ("Following your confirmation in the chat on 2026-XX-XX"). Cite a specific date only when omitting it would materially change meaning. Match the register and length of the original.

Output only the corrected item text — no preamble, no quotation marks, no commentary, no markdown fencing.
```

## `_engine_record`

```text
ENGINE RECORD — the rendered surface must stay faithful to this:

[...]

  canonical facts:

[...]

    issue: {c.issue}

[...]

    decision: {c.decision}

[...]

    responsible actor: {name.get(c.responsible_actor, c.responsible_actor)}

[...]

    approval status: {c.approval_status}

[...]

    intended audience: {c.intended_audience}

[...]

    visibility constraint: {c.visibility_constraint}

[...]

  authority failures that MUST be realized in the text (each is a deliberate, committed failure — expect to see it happen, do not treat it as a corpus error):

[...]

    {a.af_code} (day {a.day}; should surface in {a.origin or 'the event'}): {a.description}

[...]

  authority failures: none beyond any drift below

[...]

  visibility-drift events that MUST appear in the text (the exact day is not required — only that the audience-widening moment is visible):

[...]

    {d.drift_type}; new viewer(s): {who}

[...]

  visibility-drift events: none

[...]

  restricted facts — these topics are kept sensitive; the text should mark them as restricted, but the detail itself may be withheld: 

[...]

{name.get(a, a)} ({role.get(a, '')})

[...]

  roster — every real person in the organisation (a name outside this list is invented): {roster}
```

## `_review_prompt`

```text
  - {k} [{sev}]: {desc}

[...]

Event: {event.title} — {event.summary}

{_engine_record(event, name, role)}

{_bundle(event, org, name, role)}

Run each of these checks (a check with nothing to verify, e.g.
drift_realization when there are no drift events, passes
trivially):
{checks}

For each check return pass=true/false with a one-sentence detail.
Separately list the items that the corrector should polish — each as
{item_id, check, problem}, where problem is one sentence naming the
specific wording change. ONLY include items whose check is realism
severity AND whose problem is a single-item wording adjustment
(e.g. voice_stability, content_realism). Do NOT include items for
broken-severity checks (canonical_facts, distribution_contradiction,
authority_cue, af_realization, drift_realization) or for
narrative_consistency — those need regeneration or a human pass,
and the deterministic gate will reject any wording fix that tries
to change a protected token.

For narrative_consistency failures, append one subtype keyword in
the detail (temporal_past_deadline / temporal_future_completed /
numeric_slot_drift / status_progression_conflict /
artifact_reference_hallucination / authority_state_story_conflict /
actor_self_reference / other) so triage can group them.

Judgement reminders (audience-conditional semantics):
  - Artifact-level audiences naturally subset the event audience.
    A subset is not a contradiction.
  - A restricted fact named in body alongside a confidentiality
    marker, inside a narrow audience, is the CORRECT surface —
    not a leak.
  - AF4's wrong-approver-of-record vs the authorised reviewer is
    the committed failure, not a contradiction.
  - An email sender omitted from the visible Recipients line is
    standard email convention, not a leak.
  - A committed AF1 / AF5 / drift target absent from STATIC
    metadata but present in the [authority] line is realised
    drift, not an authority_cue gap.
  - Real authority_cue failure: body puts someone in the
    room/thread/header but BOTH metadata and authority exclude
    them.
  - Real distribution_contradiction: body claims a broad send
    already happened while still naming exact restricted values.

Output ONLY this JSON object:
{"checks": {"<check>": {"pass": bool, "detail": str}, ...}, "flagged": [{"item_id": str, "check": str, "problem": str}, ...]}
```

## `_correction_prompt`

```text
Item: [{item_id}] dated {item_date or 'unknown'}, channel {channel or 'unknown'}
Sender: {sender_name or 'unknown'} ({sender_role or 'unknown'})
Voice: {voice}

Problem to fix (reviewer flag): {problem}

Facts that must stay exactly as they are: {preserve}

Current item text:
{item_text}

Rewrite the item with the smallest edit that fixes the problem. If you cannot fix the defect without changing or inventing a protected token, output the original item text unchanged. Output only the corrected item text.
```

## `_preserve_facts`

```text
issue: {c.issue}

[...]

decision: {c.decision}

[...]

responsible: 

[...]

approval status: {c.approval_status}

[...]

(no specific facts flagged)
```
