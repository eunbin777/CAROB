"""ACL filter — wraps any base retriever with a per-user authority filter.

These are the canonical *security-trimming* retrievers — the asker's id
is matched against each item's allow-list directly. Two compositions
mirror the standard pre- vs post-retrieval choice documented in industry
references (Azure AI Search document-level access control / security
trimming; Pinecone RAG with access control) and recently formalised in
the academic *Authorization-First Retrieval* argument that authorization
must constrain the retrieval candidate set before any learned component
consumes content (Andersen et al., 2026).

  - :class:`PostFilterACL` runs the base retriever, then drops every result
    the asking person isn't authorized to see at the query day. Equivalent
    to industry "post-retrieval filtering / security trimming after
    retrieval".
  - :class:`PreFilterACL`  computes the authorized pool first (using
    engine truth), then runs the base retriever restricted to that pool.
    Equivalent to industry "pre-retrieval security trimming" and the
    Authorization-First Retrieval pattern.

For the role/attribute-based variant (RBAC/ABAC metadata filtering, where
the asker's *attributes* rather than her identity are matched against the
item), see :class:`orgbench.retrieval.rbac.MetadataRBACRetriever`.

Both rely on :func:`orgbench.eval.authority_resolve.visible_to`, the
single engine-truth function.

Primary references:
  - Azure AI Search Document-Level Access Control / Security Trimming
    docs (Microsoft, 2024+).
  - Pinecone RAG with Access Control (Pinecone, 2024).
  - Andersen et al. *Authorization-First Retrieval: Enforcing Least
    Privilege in Multi-Agent RAG Systems* (2026).
"""

from __future__ import annotations

from typing import Protocol

from orgbench.engine.models import Item, Organization
from orgbench.eval.authority_resolve import visible_to
from orgbench.retrieval._corpus import CorpusItem

__all__ = ["BaseRetriever", "PostFilterACL", "PreFilterACL",
           "NoisyPostFilterACL"]


class BaseRetriever(Protocol):
    """Minimal interface a retriever exposes for the ACL wrappers."""
    items: list[CorpusItem]

    def search(self, query: str, k: int = 10) -> list[str]: ...


class PostFilterACL:
    """Run base retriever → drop unauthorized hits → return top-k of survivors.

    ``events`` and ``org`` are passed in so the filter can resolve each item's
    audience via the engine record. The base retriever's ``k`` is widened
    (``k * over_fetch``) so the post-filter has enough material to fill the
    requested ``k``.
    """

    def __init__(
        self, base: BaseRetriever, events, org: Organization,
        *, over_fetch: int = 5,
    ) -> None:
        self.base = base
        self.events = list(events)
        self.org = org
        self.over_fetch = over_fetch
        self._engine_items: dict[str, Item] = {
            it.item_id: it for ev in self.events for art in ev.artifacts
            for it in art.items
        }

    def search(
        self, query: str, asking_person: str, query_day: int,
        k: int = 10,
    ) -> list[str]:
        wide = self.base.search(query, k=k * self.over_fetch)
        out: list[str] = []
        for iid in wide:
            it = self._engine_items.get(iid)
            if it is None:
                continue
            if visible_to(it, asking_person, query_day, self.org):
                out.append(iid)
                if len(out) >= k:
                    break
        return out


class NoisyPostFilterACL:
    """Stale / incomplete ACL simulation.

    Real enterprise ACLs are widely reported to be stale or over-permissive
    in production deployments (Varonis 2025 Copilot oversharing report;
    Microsoft Ignite 2024). This baseline models that pattern by treating
    each (item, asker) pair as ``visible`` with probability
    ``false_positive_rate`` regardless of the engine-truth audience --- the
    canonical "permission sprawl" failure mode.

    The decision is deterministic per ``(item_id, asking_person, seed)``
    so multiple runs of the same instance produce the same prediction.
    """

    def __init__(
        self, base: BaseRetriever, events, org: Organization,
        *, false_positive_rate: float = 0.20,
        seed: int = 42, over_fetch: int = 5,
    ) -> None:
        self.base = base
        self.events = list(events)
        self.org = org
        self.fp_rate = false_positive_rate
        self.seed = seed
        self.over_fetch = over_fetch
        self._engine_items: dict[str, Item] = {
            it.item_id: it for ev in self.events for art in ev.artifacts
            for it in art.items
        }

    def _leaks(self, item_id: str, asking_person: str) -> bool:
        # Deterministic per-(item, person, seed). hash() varies across
        # Python invocations on string inputs, so combine via a stable
        # arithmetic mix instead.
        h = 1469598103934665603  # FNV-1a 64-bit offset
        for ch in f"{item_id}|{asking_person}|{self.seed}":
            h ^= ord(ch)
            h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
        # uniform in [0, 1)
        u = (h & 0xFFFFFFFF) / float(1 << 32)
        return u < self.fp_rate

    def search(
        self, query: str, asking_person: str, query_day: int,
        k: int = 10,
    ) -> list[str]:
        wide = self.base.search(query, k=k * self.over_fetch)
        out: list[str] = []
        for iid in wide:
            it = self._engine_items.get(iid)
            if it is None:
                continue
            visible = (
                visible_to(it, asking_person, query_day, self.org)
                or self._leaks(iid, asking_person)
            )
            if visible:
                out.append(iid)
                if len(out) >= k:
                    break
        return out


class PreFilterACL:
    """Restrict the search space to items visible to the asker, then rank.

    This is the canonical "permission-aware retrieval" baseline: the
    retriever never sees forbidden items, so leak is structurally zero.
    Useful as a strong reference; in practice deployments rarely afford this
    because the visible pool needs to be recomputed per query.
    """

    def __init__(
        self, base_factory, events, org: Organization,
    ) -> None:
        """``base_factory`` is a callable ``(items) -> retriever``; it is
        called once per query with the asker's visible subset."""
        self.base_factory = base_factory
        self.events = list(events)
        self.org = org
        self.items = self._build_items()
        self._engine_items: dict[str, Item] = {
            it.item_id: it for ev in self.events for art in ev.artifacts
            for it in art.items
        }

    def _build_items(self) -> list[CorpusItem]:
        from orgbench.retrieval._corpus import build_corpus_items
        return build_corpus_items(self.events)

    def search(
        self, query: str, asking_person: str, query_day: int,
        k: int = 10,
    ) -> list[str]:
        visible_items = [
            it for it in self.items
            if (eng := self._engine_items.get(it.item_id))
            and visible_to(eng, asking_person, query_day, self.org)
        ]
        if not visible_items:
            return []
        retriever = self.base_factory(visible_items)
        return retriever.search(query, k=k)
