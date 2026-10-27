"""Oracle retriever — visible items of the queried event first, then other authorized.

Every item of the queried event that the asker may see at the query day is
placed at the top, then other authorized items fill out the top-k. This is
broader than the T2 gold ``authorized_relevant`` list, which ``T2Oracle``
reads directly and uses this ordering only to backfill. Never returns an item the
asker may not see. Used to bound how far a non-oracle retriever can go.
"""

from __future__ import annotations

from collections.abc import Sequence

from orgbench.engine.models import Event, Organization
from orgbench.eval.authority_resolve import (
    item_event_index, partition_pool,
)
from orgbench.retrieval._corpus import CorpusItem

__all__ = ["OracleRetriever"]


class OracleRetriever:
    """Returns items in the order (authorized_relevant, authorized, others).

    Needs ``queried_event_id`` per query so it knows which items count as
    relevant; the T2 oracle baseline reads it from the gold record.
    """

    def __init__(
        self, items: Sequence[CorpusItem], events: Sequence[Event],
        org: Organization,
    ) -> None:
        self.items = list(items)
        self.events = list(events)
        self.org = org
        self._event_of = item_event_index(self.events)
        self._engine_items = {
            it.item_id: it for ev in self.events for art in ev.artifacts
            for it in art.items
        }

    def search(
        self, query: str, asking_person: str, query_day: int,
        queried_event_id: str, k: int = 10,
    ) -> list[str]:
        pool_items = [self._engine_items[it.item_id] for it in self.items
                      if it.item_id in self._engine_items]
        parts = partition_pool(pool_items, asking_person, query_day, self.org,
                               queried_event_id, self._event_of)
        # authorized_relevant first, then any other authorized item
        out = list(parts["authorized_relevant"])
        for iid in parts["authorized"]:
            if iid in out:
                continue
            out.append(iid)
            if len(out) >= k:
                break
        return out[:k]
