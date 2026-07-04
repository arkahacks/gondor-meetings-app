"""Recording-title resolution: calendar name -> tab title -> meeting code.

Meet tab titles are often generic ("Meet", "Meet — abc-defg-hij"); the calendar
name is preferred when available (open question #3). Pure logic — the calendar
lookup is injected so this is unit-testable.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Protocol

from .meet import MeetingMatch

# Suffixes/prefixes Safari appends to a Meet tab title.
_MEET_SUFFIX = re.compile(r"\s*[—–\-]\s*Google Meet\s*$", re.IGNORECASE)
_MEET_PREFIX = re.compile(r"^\s*Meet\s*[—–\-]\s*", re.IGNORECASE)
_CODE = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$")


class TitleLookup(Protocol):
    def current_meeting_title(self, meet_code: str, now: _dt.datetime) -> str | None: ...


def clean_tab_title(title: str) -> str:
    t = _MEET_SUFFIX.sub("", title or "").strip()
    t = _MEET_PREFIX.sub("", t).strip()
    return t


def is_generic_tab_title(title: str, meeting_code: str | None) -> bool:
    """True when the tab title carries no meaningful meeting name."""
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower()
    if low in {"meet", "google meet", "meet.google.com"}:
        return True
    cleaned = clean_tab_title(t)
    if not cleaned:
        return True
    if _CODE.match(cleaned.lower()):
        return True
    if meeting_code and cleaned.lower() == meeting_code.lower():
        return True
    return False


def resolve_title(
    match: MeetingMatch,
    now: _dt.datetime,
    sources: tuple[str, ...] | list[str],
    calendar_lookup: TitleLookup | None,
    append_timestamp: bool,
) -> str:
    """Resolve a recording title from the configured sources (first hit wins)."""
    base: str | None = None
    for src in sources:
        if src == "calendar":
            if match.meeting_code and calendar_lookup is not None:
                found = calendar_lookup.current_meeting_title(match.meeting_code, now)
                if found:
                    base = found.strip()
                    break
        elif src == "tab":
            if not is_generic_tab_title(match.title, match.meeting_code):
                base = clean_tab_title(match.title)
                break
        elif src == "code":
            base = match.meeting_code or "Google Meet"
            break

    if not base:
        base = match.meeting_code or "Meeting"

    if append_timestamp:
        base = f"{base} — {now.strftime('%Y-%m-%d %H:%M')}"
    return base
