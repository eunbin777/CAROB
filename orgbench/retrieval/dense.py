"""Dense retrieval backend (sentence-transformers, lazy-loaded).

Optional — requires ``sentence-transformers`` (and a model checkpoint at
first use). Same interface as :class:`bm25.BM25Retriever`. Two indexing
variants again — text-only / with-metadata.

Defaults to ``BAAI/bge-base-en-v1.5`` which is small, fast, and competitive
on BEIR-style retrieval.
"""

from __future__ import annotations

from collections.abc import Sequence

from orgbench.retrieval._corpus import CorpusItem

__all__ = ["DenseRetriever"]


class DenseRetriever:
    """Cosine-similarity retriever over sentence-transformer embeddings."""

    def __init__(
        self, items: Sequence[CorpusItem], *,
        model_name: str = "BAAI/bge-base-en-v1.5",
        include_metadata: bool = False,
        device: str | None = None,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError as exc:                       # pragma: no cover
            raise ImportError(
                "The dense_bge baseline needs the 'sentence-transformers' "
                "package. Install it with: pip install -r requirements-dense.txt"
            ) from exc

        self.items = list(items)
        self.include_metadata = include_metadata
        self.model_name = model_name
        self._model = SentenceTransformer(model_name, device=device)
        docs = [self._doc_text(it) for it in self.items]
        # normalize_embeddings=True so dot product == cosine similarity
        self._doc_embeddings = self._model.encode(
            docs, batch_size=32, normalize_embeddings=True,
            show_progress_bar=False, convert_to_numpy=True)
        self._np = np

    def _doc_text(self, it: CorpusItem) -> str:
        if self.include_metadata and it.metadata_blob:
            return f"{it.metadata_blob}\n{it.text}"
        return it.text

    def search(self, query: str, k: int = 10) -> list[str]:
        if not query.strip():
            return []
        q_emb = self._model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True)[0]
        scores = self._doc_embeddings @ q_emb        # cosine sim
        order = sorted(range(len(self.items)),
                       key=lambda i: (-float(scores[i]), self.items[i].item_id))
        return [self.items[i].item_id for i in order[:k]]
