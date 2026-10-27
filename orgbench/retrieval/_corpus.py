"""Shared corpus view for retrievers.

A retriever operates over a flat list of items. For each item we keep the
item id, its text body, and a compact metadata string that callers can opt
to include in the search signal (recipients, attendees, sharing list,
form header). Two indexing variants are produced — text-only and
text+metadata — so the experiments can show the metadata effect explicitly.

This module also exposes ``Item``-like records the retrievers consume
without needing the engine dataclasses.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from orgbench.engine.models import Artifact, Event, Item

__all__ = [
    "CorpusItem", "build_corpus_items",
    "render_item_text", "render_item_metadata_blob",
]


@dataclass
class CorpusItem:
    """One retrieval-ready record."""
    item_id: str
    artifact_id: str
    event_id: str
    channel: str
    day: int
    date: str
    sender: str | None
    text: str                       # body text (the LLM-rendered surface)
    metadata_blob: str              # short string of recipients / attendees /
                                    # sharing list / form-header fields


def render_item_text(item: Item) -> str:
    return (item.text or "").strip()


def render_item_metadata_blob(artifact: Artifact) -> str:
    """One-line metadata signal a sparse retriever can index on top of body."""
    md = artifact.metadata
    parts: list[str] = []
    if artifact.channel_type == "chat" and md.channel_members:
        parts.append("members: " + ", ".join(md.channel_members))
    if artifact.channel_type in ("email", "approval") and md.recipients:
        for k in ("to", "cc", "bcc"):
            v = md.recipients.get(k) or []
            if v:
                parts.append(f"{k}: " + ", ".join(v))
    if artifact.channel_type == "meeting" and md.attendees:
        parts.append("attendees: " + ", ".join(md.attendees))
    if artifact.channel_type == "document" and md.sharing_list:
        parts.append("shared with: " + ", ".join(md.sharing_list))
    if artifact.channel_type == "ticket" and md.project_visibility:
        parts.append(f"project: {md.project_visibility}")
    f = artifact.form
    if f.title:
        parts.append(f"title: {f.title}")
    if f.subject:
        parts.append(f"subject: {f.subject}")
    if f.assignee:
        parts.append(f"assignee: {f.assignee}")
    if f.approver:
        parts.append(f"approver: {f.approver}")
    if f.prepared_by:
        parts.append("prepared by: " + ", ".join(f.prepared_by))
    if f.reviewed_by:
        parts.append("reviewed by: " + ", ".join(f.reviewed_by))
    return " | ".join(parts)


def build_corpus_items(events: Iterable[Event]) -> list[CorpusItem]:
    """Flatten ``events`` into a list of retrieval-ready ``CorpusItem``s."""
    out: list[CorpusItem] = []
    for ev in events:
        for art in ev.artifacts:
            blob = render_item_metadata_blob(art)
            for it in art.items:
                out.append(CorpusItem(
                    item_id=it.item_id,
                    artifact_id=art.artifact_id,
                    event_id=ev.event_id,
                    channel=art.channel_type,
                    day=it.day,
                    date=it.date,
                    sender=it.sender,
                    text=render_item_text(it),
                    metadata_blob=blob,
                ))
    return out
