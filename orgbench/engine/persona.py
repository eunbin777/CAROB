"""Step 1 — persona (writing profile) assignment.

Each employee gets three style axes (formality, verbosity, register) plus one
brief *character trait*. A trait ("detail-oriented and precise") shapes how a
person tends to write but is applied loosely — people adapt to the situation —
unlike a rigid mechanical quirk applied to every message.

The axes are cycled so 24-56 employees spread evenly. To exercise the engine
without LLM calls, :func:`stub_persona_text` produces deterministic persona
text.
"""

from __future__ import annotations

from itertools import cycle
from typing import Callable

from .models import Employee, Organization
from .rng import rng_for

__all__ = [
    "PERSONALITY_POOL", "assign_persona_axes", "stub_persona_text",
    "populate_personas",
]

PERSONALITY_POOL = [
    "detail-oriented and precise",
    "warm and encouraging",
    "direct and to-the-point",
    "diplomatic and measured",
    "fast-moving and action-focused",
    "analytical and cautious",
    "big-picture and strategic",
    "collaborative and consensus-seeking",
    "skeptical and probing",
    "pragmatic and no-nonsense",
    "calm and reassuring",
    "thorough and methodical",
]


def assign_persona_axes(employees: list[Employee], seed: int) -> None:
    """Assign the three style axes and one character trait, in place.

    formality / verbosity / register are cycled for even coverage; the
    personality trait is sampled per employee.
    """
    formality = cycle(["formal", "casual"])
    verbosity = cycle(["concise", "verbose"])
    register = cycle(["technical", "colloquial"])
    for emp in employees:
        emp.persona.formality = next(formality)
        emp.persona.verbosity = next(verbosity)
        emp.persona.register = next(register)
        emp.persona.personality = rng_for(
            seed, "personality", emp.emp_id).choice(PERSONALITY_POOL)


def stub_persona_text(emp: Employee) -> str:
    """Deterministic, LLM-free persona text. Reads as a character, not a tic."""
    p = emp.persona
    return (
        f"{emp.name} comes across as {p.personality}. They write in a "
        f"{p.formality}, {p.register} register and tend to be {p.verbosity}."
    )


def populate_personas(
    org: Organization,
    text_fn: Callable[[Employee], str] = stub_persona_text,
) -> None:
    """Fill ``persona.frozen_text`` for every employee, then freeze it."""
    for emp in org.employees:
        emp.persona.frozen_text = text_fn(emp)
