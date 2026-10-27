"""Step 1 — organizational calendar + business-day date helper.

A trivial time window. Events carry their own ``start_day`` (assigned from the
Step 1 work portfolio); the calendar records the window length and the real
calendar date that business-day 1 maps to.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from .models import OrganizationalCalendar

__all__ = ["build_calendar", "business_date"]


def build_calendar(cfg: dict) -> OrganizationalCalendar:
    corpus = cfg["corpus"]
    total = corpus["total_days"]
    return OrganizationalCalendar(
        total_days=total,
        start_date=corpus.get("start_date", "2026-01-05"),
        quarter_starts=[1, total // 3 + 1, 2 * total // 3 + 1],
    )


@lru_cache(maxsize=4096)
def business_date(start_iso: str, day: int) -> str:
    """Real calendar date (YYYY-MM-DD) of business-day ``day`` (day 1 = start).

    Weekends are skipped, so consecutive business days stay on weekdays.
    """
    d = date.fromisoformat(start_iso)
    advanced = 0
    while advanced < max(0, day - 1):
        d += timedelta(days=1)
        if d.weekday() < 5:                  # Mon-Fri
            advanced += 1
    return d.isoformat()
