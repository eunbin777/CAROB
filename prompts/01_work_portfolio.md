# Step 1 — work portfolio

Elicits the quarter's projects and events for the simulated organization (frozen afterwards).

Verbatim prompt text from the generation pipeline that built CAROB. Text in `{...}` is filled by the deterministic engine at run time. Sections are listed in the order the pipeline assembles them; `[...]` separates string pieces that the pipeline joins with run-time content. Strings that serve only as code (dictionary keys, status labels, patterns) are left out.

## `_SYSTEM`

```text
You plan a realistic quarter of work for a synthetic enterprise. You output structured JSON only. Be diverse and concrete: a real org runs many different kinds of work at once, not variations of one thing.
```

## `build_portfolio_prompt`

```text
  {t.team_id} - {t.name}

[...]

Organization: {org.name}
  profile: {org.company_type}, {org.size_band}, {org.work_arrangement}
  teams:
{teams}
  headcount: {len(org.employees)}

Plan this org's work over a {window}-business-day window.

Produce:
  - {pf['n_projects']} projects: substantial multi-event work threads that
    each run for much of the window and contain about 10-14 related events
    (planning, reviews, builds, audits, incidents, sign-offs, etc.) — a real
    project has many sub-matters, not just a handful.
  - {pf['n_events']} events total. About four fifths belong to a project;
    the rest are standalone (incidents, escalations, one-off approvals,
    hiring, etc.). Events of the SAME type must be genuinely different in
    subject — avoid near-duplicates.

event_type must be one of:
  {types}

Return a single JSON object:
{
  "projects": [
    {"project_id": "P_shortname", "name": "...", "description": "one line",
      "lead_team": "T_xxx"}
  ],
  "events": [
    {"title": "concrete event title",
      "event_type": "<from the list>",
      "project_id": "P_shortname" or null,
      "start_day": <int, 1..{pf['latest_start_day']}>,
      "summary": "one-line description of what this event is about",
      "involves_approval": true or false,
      "sensitivity": "routine" or "confidential" or "restricted"}
  ]
}

Rules:
  - project_id on an event must be null or match a project above
  - start_day within [1, {pf['latest_start_day']}]; spread events across
    the window; a project's events should be in roughly chronological order
  - titles and summaries are specific and realistic for this kind of company
  - involves_approval: true if the event runs a formal approval / sign-off —
    a deliverable is reviewed and signed off (a budget, a hire, a vendor, a
    launch, a policy exception, an audit report). false if it concludes
    without a formal approval (an operational response, coordination, or
    status work). Decide from what the event actually is; be realistic — a
    fair share of real events have no formal sign-off.
  - sensitivity: "routine" for ordinary team-internal work; "confidential"
    for a limited audience (compensation, finances, strategy); "restricted"
    for tightly held matters (security incidents, legal disputes, exec-only).
  - do NOT name real products or vendors (no Slack, Jira, AWS, etc.)
  - output ONLY the JSON object.
```

## `_correction_message`

```text
The previous portfolio JSON had these problems:
{bullets}
Regenerate the COMPLETE JSON, fixing them. Output only the JSON.
```
