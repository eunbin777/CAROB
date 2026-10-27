"""Step 1 — organization builder.

Teams, roles, headcounts, channels and access policy come from the hand-spec
(``config/org_spec.yaml``). Individual employees are generated procedurally
from the role templates: deterministic names from a fixed pool, seeded
seniority. This keeps the hand-spec short while scaling cleanly — to go from
24 to 56 employees, only the role ``count`` values change.
"""

from __future__ import annotations

from pathlib import Path

from .config import load_yaml
from .models import Channel, Employee, Organization, Team
from .rng import rng_for

__all__ = ["build_organization", "FIRST_NAMES", "LAST_NAMES"]

# Fixed name pools (>= 56 each) so every employee gets a distinct first+last
# pair by index — no de-duplication needed.
FIRST_NAMES = [
    "Alice", "Bob", "Carol", "David", "Emma", "Frank", "Grace", "Henry",
    "Irene", "Jack", "Karen", "Liam", "Mia", "Noah", "Olivia", "Peter",
    "Quinn", "Rachel", "Sam", "Tina", "Umar", "Vera", "Wei", "Xena",
    "Yusuf", "Zoe", "Aarav", "Bianca", "Chen", "Diego", "Elena", "Farah",
    "Gabriel", "Hana", "Ivan", "Julia", "Kenji", "Lucia", "Marco", "Nadia",
    "Omar", "Priya", "Rohan", "Sofia", "Tomas", "Uma", "Victor", "Wendy",
    "Ximena", "Yara", "Zane", "Amara", "Bruno", "Clara", "Dmitri", "Esra",
    "Felix", "Gita", "Hugo", "Ingrid", "Jamal", "Keira", "Leon", "Maya",
]
LAST_NAMES = [
    "Kim", "Lee", "Park", "Choi", "Nguyen", "Patel", "Garcia", "Smith",
    "Johnson", "Wang", "Mueller", "Rossi", "Andersen", "Okafor", "Silva",
    "Tanaka", "Cohen", "Murphy", "Khan", "Dubois", "Novak", "Costa",
    "Haddad", "Sato", "Reyes", "Brown", "Fischer", "Ivanov", "Mehta",
    "Yamamoto", "Lopez", "Walsh", "Bauer", "Singh", "Moreau", "Petrov",
    "Adebayo", "Romano", "Hansen", "Cruz", "Becker", "Jensen", "Marchetti",
    "Osei", "Schmidt", "Vargas", "Wagner", "Eriksson", "Bianchi", "Hoffmann",
    "Nakamura", "Pereira", "Sokolov", "Abebe", "Lindqvist", "Ferrari",
    "Kowalski", "Delgado", "Ahmed", "Larsen", "Bennett", "Conti", "Dominguez",
    "Fontaine",
]


def build_organization(cfg: dict, root: Path) -> Organization:
    """Build the :class:`Organization` (people, teams, channels, profile).

    Persona text, calendar and projects are attached later in Step 1.
    """
    seed = cfg["master_seed"]
    spec = load_yaml(root / cfg["paths"]["org_spec"])
    profile = cfg["organization"]

    org = Organization(
        org_id="ORG_1",
        name="Enterprise AI Vendor",
        company_type=profile["company_type"],
        size_band=profile["size_band"],
        work_arrangement=profile["work_arrangement"],
        access_policy_profile=profile["access_policy_profile"],
        master_seed=seed,
    )

    # --- shuffle name pools once, deterministically -----------------------
    name_rng = rng_for(seed, "names")
    firsts = FIRST_NAMES[:]
    lasts = LAST_NAMES[:]
    name_rng.shuffle(firsts)
    name_rng.shuffle(lasts)

    # --- teams + procedural employees ------------------------------------
    idx = 0
    for team_spec in spec["teams"]:
        team = Team(team_id=team_spec["team_id"], name=team_spec["name"])
        org.teams.append(team)
        for role in team_spec["roles"]:
            for _ in range(role["count"]):
                if idx >= len(firsts) or idx >= len(lasts):
                    raise ValueError(
                        "name pool exhausted; extend FIRST_NAMES/LAST_NAMES")
                first, last = firsts[idx], lasts[idx]
                emp_id = f"E_{first.lower()}"
                lo, hi = role["seniority"]
                seniority = rng_for(seed, "seniority", emp_id).randint(lo, hi)
                emp = Employee(
                    emp_id=emp_id,
                    name=f"{first} {last}",
                    team_id=team.team_id,
                    role=role["title"],
                    seniority_years=seniority,
                )
                org.employees.append(emp)
                if role.get("lead"):
                    team.lead_emp_id = emp_id
                idx += 1

    expected = cfg["corpus"]["n_employees"]
    if idx != expected:
        raise ValueError(
            f"org_spec role counts sum to {idx} but "
            f"corpus.n_employees is {expected}")

    org.channels = _build_channels(spec, org)
    return org


def _build_channels(spec: dict, org: Organization) -> list[Channel]:
    """Standing chat channels: org-wide, leads, cross-functional, per-team."""
    channels: list[Channel] = []
    team_vis = {t["team_id"]: t.get("chat_visibility", "team")
                for t in spec["teams"]}

    for ch in spec.get("channels", []):
        scope = ch.get("scope", "org")
        if scope == "org":
            channels.append(Channel(
                channel_id=ch["channel_id"],
                channel_type=ch["channel_type"],
                name=ch["name"],
                members=[e.emp_id for e in org.employees],
                default_visibility=ch.get("default_visibility", "org"),
            ))
        elif scope == "leads":
            channels.append(Channel(
                channel_id=ch["channel_id"],
                channel_type=ch["channel_type"],
                name=ch["name"],
                members=[t.lead_emp_id for t in org.teams if t.lead_emp_id],
                default_visibility=ch.get("default_visibility", "restricted"),
            ))
        elif scope == "cross":
            member_teams = ch.get("member_teams", [])
            members = sorted(
                e.emp_id for e in org.employees
                if e.team_id in member_teams
            )
            channels.append(Channel(
                channel_id=ch["channel_id"],
                channel_type=ch["channel_type"],
                name=ch["name"],
                members=members,
                default_visibility=ch.get("default_visibility", "team"),
            ))

    # one chat channel per team — short lowercase names like a real Slack
    _TEAM_SLUG = {
        "Executive": "exec", "Product": "product", "Engineering": "engineering",
        "Sales": "sales", "Security": "security", "Legal": "legal",
        "Customer Success": "customer-success", "Finance": "finance",
    }
    for team in org.teams:
        slug = _TEAM_SLUG.get(team.name, team.name.lower().replace(" ", "-"))
        channels.append(Channel(
            channel_id=f"C_{team.team_id}",
            channel_type="chat",
            name=slug,
            members=sorted(org.team_members(team.team_id)),
            default_visibility=team_vis.get(team.team_id, "team"),
        ))
    return channels
