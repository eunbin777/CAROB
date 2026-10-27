"""BM25 retrieval backend (lexical, sparse).

Two indexing variants are exposed:

  - ``text_only``     : index body text only — same signal richness as the
    EnronQA benchmark, used for calibration sanity.
  - ``with_metadata`` : index body text + visible-metadata blob (recipients /
    attendees / sharing list / form header). Captures the structured
    metadata signal our corpus exposes that EnronQA does not.

Both variants ignore authority — they are relevance-only retrievers. ACL
variants live in :mod:`acl_filter`.

Tokenization is intentionally simple (lowercase, alpha-num split) so the
behaviour matches the rank_bm25 default examples reviewers will be familiar
with.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from orgbench.retrieval._corpus import CorpusItem

__all__ = ["BM25Retriever"]


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(s)]


class BM25Retriever:
    """Wraps rank_bm25.BM25Okapi over a flat corpus of items."""

    def __init__(
        self, items: Sequence[CorpusItem], *,
        include_metadata: bool = False,
    ) -> None:
        self.items = list(items)
        self.include_metadata = include_metadata
        docs = [_tokenize(self._doc_text(it)) for it in self.items]
        # rank_bm25 chokes on a corpus with empty documents; substitute a
        # single zero token so the index can be built.
        self._bm25 = BM25Okapi([d or ["_empty"] for d in docs])

    def _doc_text(self, it: CorpusItem) -> str:
        if self.include_metadata and it.metadata_blob:
            return f"{it.metadata_blob}\n{it.text}"
        return it.text

    def search(
        self, query: str, k: int = 10,
    ) -> list[str]:
        """Return up to ``k`` item_ids ranked by BM25 score (best first)."""
        return [iid for iid, _ in self.search_with_scores(query, k=k)]

    def search_with_scores(
        self, query: str, k: int = 10,
    ) -> list[tuple[str, float]]:
        """Like :meth:`search` but also returns the BM25 score. Used by the
        hybrid fusion and the namespace merge."""
        q = _tokenize(query)
        if not q:
            return []
        scores = self._bm25.get_scores(q)
        order = sorted(range(len(self.items)),
                       key=lambda i: (-scores[i], self.items[i].item_id))
        return [(self.items[i].item_id, float(scores[i])) for i in order[:k]]
