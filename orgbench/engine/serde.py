"""Generic JSON (de)serialization for the dataclass corpus model.

``to_dict`` / ``from_dict`` round-trip any nested combination of dataclasses,
lists, dicts and ``X | None`` optionals. This keeps the model itself free of
serialization boilerplate while still producing readable JSON corpus files.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from pathlib import Path

__all__ = ["to_dict", "from_dict", "save_json", "load_json"]


def to_dict(obj: object) -> object:
    """Recursively convert dataclasses/lists/dicts into JSON-ready data."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, str):
        # drop lone UTF-16 surrogates an LLM occasionally emits; they cannot
        # be UTF-8 encoded and would otherwise crash the JSON write
        return obj.encode("utf-8", "ignore").decode("utf-8")
    return obj


def _is_union(origin: object) -> bool:
    return origin is typing.Union or origin is types.UnionType


def from_dict(tp: object, data: object) -> object:
    """Recursively rebuild a typed object of type ``tp`` from plain data."""
    origin = typing.get_origin(tp)

    if _is_union(tp) or _is_union(origin):
        if data is None:
            return None
        non_none = [a for a in typing.get_args(tp) if a is not type(None)]
        return from_dict(non_none[0], data)

    if origin in (list, tuple):
        args = typing.get_args(tp)
        item_tp = args[0] if args else typing.Any
        return [from_dict(item_tp, v) for v in data]

    if origin is dict:
        args = typing.get_args(tp)
        val_tp = args[1] if len(args) == 2 else typing.Any
        return {k: from_dict(val_tp, v) for k, v in data.items()}

    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        hints = typing.get_type_hints(tp)
        kwargs = {
            f.name: from_dict(hints[f.name], data[f.name])
            for f in dataclasses.fields(tp)
            if f.name in data
        }
        return tp(**kwargs)

    return data


def save_json(obj: object, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(to_dict(obj), fh, ensure_ascii=False, indent=2)


def load_json(tp: object, path: str | Path) -> object:
    with Path(path).open("r", encoding="utf-8") as fh:
        return from_dict(tp, json.load(fh))
