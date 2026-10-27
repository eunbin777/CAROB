"""Retrieval backends — pure retrievers operating over the full corpus.

The corpus is the flat item set built by :func:`_corpus.build_corpus_items`
(item text + visible metadata + form header). Two interfaces:

    # relevance-only (ignores authority)
    ranked_ids = BM25Retriever(items).search(query, k=10)

    # authority-aware (consults the engine record for the asker at the day)
    ranked_ids = retriever.search(query, asking_person, query_day, k=10)

Backends:
  - :mod:`bm25`        — sparse, lexical (rank_bm25); text-only or
                         text + visible metadata
  - :mod:`dense`       — BGE embeddings (sentence-transformers, optional)
  - :mod:`acl_filter`  — per-user ACL security trim (pre / post) and the
                         noisy (over-permissive) post-filter
  - :mod:`rbac`        — team-attribute (RBAC) metadata filter
  - :mod:`namespace`   — team-partitioned indexes
  - :mod:`hybrid`      — reciprocal-rank fusion followed by an ACL pass
  - :mod:`oracle`      — engine-ranked authorised items, the ceiling reference
"""
