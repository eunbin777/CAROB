"""Role-/Attribute-based metadata filter retriever.

A separate family from per-user ACL filters (``PreFilterACL`` /
``PostFilterACL``). Instead of matching the asker's individual id against a
document's allow-list, this retriever matches the asker's *attributes*
(team, role, optionally clearance) against the *attributes* the document
requires — the canonical RBAC/ABAC pattern formalised by Sandhu et al.
(1996) and instantiated in modern RAG systems by Jeong & Lee (2025,
*Permission-Aware RAG*) and Chen & Taipalus (2025, *Metadata-aware RAG
for Enforcing Access Control*).

The two mechanisms are not equivalent. A per-user ACL accepts the asker
iff she is explicitly listed in ``audience.include_emps``; a team-RBAC
filter accepts the asker iff *some teammate* of hers is listed. This is a
deliberately coarser, more deployable approximation — the trade-off the
RBAC literature has analysed since 1996. In our corpus the comparison
exercises exactly this gap: items whose ``audience.include_emps`` excludes
the asker but includes a teammate will be retrievable here but not by
:class:`PreFilterACL`.

We instantiate the simplest concrete RBAC: ``team_id`` is the only
attribute. The audience teams of an item are computed once at index time
(``teams(item) = { team_of(emp) : emp ∈ audience_emps(item) }``); at
query time the asker's team is checked against this set. An ABAC
extension that adds role/clearance attributes is straightforward but not
implemented here because our employees only carry team membership as a
hard attribute — adding a fabricated clearance tier would compromise the
"engine truth" stance of our gold.

Primary references:
  - Sandhu, Coyne, Feinstein & Youman (1996). *Role-Based Access Control
    Models*. IEEE Computer.
  - Jeong & Lee (2025). *Permission-Aware RAG: IAM-Based Access Filtering
    in Multi-Resource Environments*. IEEE Access.
  - Chen & Taipalus (2025). *Metadata-aware RAG for Enforcing Access
    Control and Metadata-based Filtering: Proof of Concept and Evaluation*.
    RACS.
"""

from __future__ import annotations

from collections.abc import Sequence

from orgbench.engine.models import Event, Item, Organization
from orgbench.retrieval._corpus import CorpusItem
from orgbench.retrieval.bm25 import BM25Retriever

__all__ = ["MetadataRBACRetriever"]


class MetadataRBACRetriever:
    """Search BM25-wide, accept items whose attribute set intersects the
    asker's. Attribute = team membership.

    Concretely: each item is tagged at index time with the set of
    ``team_id``s whose members appear in its audience; the asker's
    ``team_id`` is the lone query-time attribute. An item is retrievable
    iff the asker's team is in the item's tagged set.

    Parameters
    ----------
    items : flat list of :class:`CorpusItem`
    events : engine events, used once to compute per-item audience teams
    org : organisation (for the employee → team map)
    include_metadata : whether the BM25 index also reads the visible
        metadata blob (default False; mirrors :class:`BM25Retriever`)
    over_fetch : factor on ``k`` so the filter has enough material to
        return ``k`` survivors (default 5)
    """

    def __init__(
        self, items: Sequence[CorpusItem], events: Sequence[Event],
        org: Organization, *,
        include_metadata: bool = False, over_fetch: int = 5,
    ) -> None:
        self.items = list(items)
        self.events = list(events)
        self.org = org
        self.over_fetch = over_fetch
        self._team_of = {e.emp_id: e.team_id for e in org.employees}
        engine_items: dict[str, Item] = {
            it.item_id: it for ev in self.events for art in ev.artifacts
            for it in art.items
        }
        # precompute item.id -> {team_id, ...} the item is reachable from
        self._teams_of_item: dict[str, set[str]] = {}
        for it in self.items:
            eng = engine_items.get(it.item_id)
            if eng is None or eng.authority is None:
                continue
            try:
                aud = eng.authority.audience_at(eng.day)
            except ValueError:
                continue
            audience = aud.resolve(org)
            self._teams_of_item[it.item_id] = {
                t for t in (self._team_of.get(emp) for emp in audience) if t
            }
        self._base = BM25Retriever(items, include_metadata=include_metadata)

    def _user_attributes(self, asking_person: str) -> set[str]:
        tid = self._team_of.get(asking_person)
        return {tid} if tid else set()

    def search(
        self, query: str, asking_person: str, query_day: int,
        k: int = 10,
    ) -> list[str]:
        attrs = self._user_attributes(asking_person)
        if not attrs:
            return []
        wide = self._base.search(query, k=k * self.over_fetch)
        out: list[str] = []
        for iid in wide:
            item_teams = self._teams_of_item.get(iid, set())
            if attrs & item_teams:
                out.append(iid)
                if len(out) >= k:
                    break
        return out
