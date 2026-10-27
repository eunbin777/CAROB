"""Namespace / federated retrieval — separate indexes per permission domain.

A widely deployed enterprise pattern: instead of one global index over the
corpus, partition the corpus into segments by an access-control domain
(team membership, tenant, project) and keep one index per segment. A query
fans out to the segments the asker belongs to and merges the per-segment
top-k.

Multiple sources describe the same idea under different names:

  - Pinecone calls it *namespace* — "store embeddings in each user's
    namespace and restrict retrieval to that namespace".
  - Mavic Labs (Multi-Tenant RAG, 2026) calls the strongest variant the
    *Silo model* — "separate index per tenant" with "higher cost, higher
    isolation".
  - RAGAboutIt (Permission-Based Retrieval at Scale) calls the same
    architecture *Federated Retrieval* — "separate indexes for different
    permission domains; each domain index is optimized for its permission
    model".

We segment by ``team_id`` because every employee in our org belongs to one
team, and every item's audience is recoverable to the set of teams whose
members can see it. An item is indexed in every segment of a team with at
least one audience member; an asker's query is dispatched to the segment of
her own team.

Trade-offs (reported in the literature):
  - **+ structural isolation**: segments other than the asker's are
    *physically unreachable*, so a forbidden item is structurally
    impossible to retrieve from outside the asker's segments.
  - **− recall on cross-domain items**: an item whose audience straddles
    domains may live in two segments; segmenting by team is consistent but
    not lossless if an item is meant for a coalition the asker is not on.

Implementation: one :class:`BM25Retriever` per team segment, plus a
deterministic ``employee → team → segments`` map.
"""

from __future__ import annotations

from collections.abc import Sequence

from orgbench.engine.models import Event, Organization
from orgbench.retrieval._corpus import CorpusItem
from orgbench.retrieval.bm25 import BM25Retriever

__all__ = ["NamespaceRetriever"]


class NamespaceRetriever:
    """Federated retrieval over team-scoped namespaces.

    Each team_id gets its own BM25 index built from items whose audience
    includes at least one team member. A query from an asker is dispatched
    to the asker's own team segment and the hits are ranked by score for
    the final top-k.

    Limitations (acknowledged): a team-only namespace misses items that
    belong to a cross-team coalition that the asker is not a member of.
    This is the realistic deployment trade-off — federated retrievers
    cannot recover items outside their permission domain.
    """

    def __init__(
        self, items: Sequence[CorpusItem], events: Sequence[Event],
        org: Organization, *, include_metadata: bool = False,
    ) -> None:
        self.items = list(items)
        self.org = org
        self.include_metadata = include_metadata
        team_of = {e.emp_id: e.team_id for e in org.employees}
        # collect every employee that appears in any item's audience and
        # bucket items by the teams those employees belong to.
        engine_items = {
            it.item_id: it for ev in events for art in ev.artifacts
            for it in art.items
        }
        self._team_index: dict[str, list[CorpusItem]] = {}
        for it in self.items:
            eng = engine_items.get(it.item_id)
            if eng is None or eng.authority is None:
                continue
            # the *first* audience entry holds the item's birth audience —
            # using `audience_at(item.day)` gives the state at creation,
            # which is what a per-team index would commit to.
            try:
                aud = eng.authority.audience_at(eng.day)
            except ValueError:
                continue
            audience_emps = aud.resolve(org)
            seen_teams: set[str] = set()
            for emp_id in audience_emps:
                tid = team_of.get(emp_id)
                if tid and tid not in seen_teams:
                    seen_teams.add(tid)
                    self._team_index.setdefault(tid, []).append(it)
        # one BM25 per team
        self._team_retrievers: dict[str, BM25Retriever] = {
            tid: BM25Retriever(items, include_metadata=include_metadata)
            for tid, items in self._team_index.items()
        }
        self._asker_team = team_of

    def _asker_segments(self, asking_person: str) -> list[str]:
        tid = self._asker_team.get(asking_person)
        return [tid] if tid else []

    def search(
        self, query: str, asking_person: str, query_day: int,
        k: int = 10,
    ) -> list[str]:
        segments = self._asker_segments(asking_person)
        if not segments:
            return []
        # merge per-segment top-k by BM25 score; segments are searched with
        # the same query, so scores are comparable.
        scored: list[tuple[str, float]] = []
        seen: set[str] = set()
        for tid in segments:
            retriever = self._team_retrievers.get(tid)
            if retriever is None:
                continue
            for iid, score in retriever.search_with_scores(query, k=k * 2):
                if iid in seen:
                    continue
                seen.add(iid)
                scored.append((iid, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [iid for iid, _ in scored[:k]]
