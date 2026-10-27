"""Hybrid retrieve-filter-rerank — fusion of multiple base retrievers with
an ACL pass.

RAGAboutIt (*Permission-Based Retrieval at Scale: 3 Architectural Patterns*)
describes a hybrid pattern as:

    "Retrieve 100-200 documents without permission filtering, apply
    permission-based filtering to that candidate pool, rerank results by
    relevance within the permission-compliant subset."

In production this is the most common pattern when permissions change
quickly or fine-grained ABAC rules apply per query. The reranker is usually
a different signal from the wide-retrieval scorer — a cross-encoder or a
second retriever — so the final order is not just "first match that
happens to be permitted".

We implement the canonical hybrid as: (i) every base retriever retrieves
wide top-K candidates with scores, (ii) candidates are fused via
Reciprocal Rank Fusion, (iii) the ACL pass drops anything not visible at
the query day, (iv) the surviving items keep their fused-rank order.

Reciprocal Rank Fusion (Cormack, Clarke & Buettcher 2009) is the standard
hybrid-fusion baseline: for each retriever, an item's contribution is
``1 / (rrf_k + rank)``; the sum across retrievers determines the final
rank. We use the conventional ``rrf_k = 60``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from orgbench.engine.models import Event, Item, Organization
from orgbench.eval.authority_resolve import visible_to

__all__ = ["HybridRetrieveFilterRerank"]

_RRF_K = 60                                    # standard RRF smoothing


class _ScoringRetriever(Protocol):
    def search_with_scores(
        self, query: str, k: int,
    ) -> Sequence[tuple[str, float]]: ...


class HybridRetrieveFilterRerank:
    """Hybrid retrieval: RRF fusion of base retrievers → ACL filter → top-k.

    Parameters
    ----------
    retrievers : list of base retrievers exposing ``search_with_scores``;
        e.g. ``[BM25 text-only, BM25 with-metadata]``
    events, org : engine record for the visibility check
    k_wide : retrieve this many per base retriever before fusion
        (RAGAboutIt suggests 100-200; we default to 50 because our corpus
        is on the order of 3k items)
    """

    def __init__(
        self, retrievers: Sequence[_ScoringRetriever],
        events: Sequence[Event], org: Organization,
        *, k_wide: int = 50,
    ) -> None:
        if not retrievers:
            raise ValueError("at least one base retriever is required")
        self.retrievers = list(retrievers)
        self.events = list(events)
        self.org = org
        self.k_wide = k_wide
        self._engine_items: dict[str, Item] = {
            it.item_id: it for ev in self.events for art in ev.artifacts
            for it in art.items
        }

    def search(
        self, query: str, asking_person: str, query_day: int,
        k: int = 10,
    ) -> list[str]:
        # (i) wide retrieval per base, with ranks
        rrf_score: dict[str, float] = {}
        for retriever in self.retrievers:
            scored = retriever.search_with_scores(query, k=self.k_wide)
            for rank, (iid, _score) in enumerate(scored, start=1):
                rrf_score[iid] = rrf_score.get(iid, 0.0) + 1.0 / (_RRF_K + rank)
        # (ii) sort by fused score (desc), tie-break by item_id
        fused = sorted(rrf_score.items(), key=lambda kv: (-kv[1], kv[0]))
        # (iii) ACL pass
        out: list[str] = []
        for iid, _ in fused:
            it = self._engine_items.get(iid)
            if it is None:
                continue
            if visible_to(it, asking_person, query_day, self.org):
                out.append(iid)
                if len(out) >= k:
                    break
        return out
