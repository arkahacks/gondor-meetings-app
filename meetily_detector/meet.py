"""Meeting-URL classification and meeting-code extraction (pure logic)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# The meeting code lives in the path of a real Meet call URL: meet.google.com/xxx-xxxx-xxx
# Landing page (meet.google.com/) and meet.google.com/new must NOT match.
_MEET_CODE_IN_URL = re.compile(r"https://meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})\b")


@dataclass(frozen=True)
class PlatformRule:
    name: str
    enabled: bool
    url_regex: str

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.url_regex)


@dataclass(frozen=True)
class MeetingMatch:
    """A tab that matched a platform rule and is a candidate for recording."""

    platform: str
    url: str
    title: str
    frontmost: bool
    meeting_code: str | None


def extract_meet_code(url: str) -> str | None:
    """Return the Google Meet meeting code from a URL, or None if absent."""
    m = _MEET_CODE_IN_URL.search(url or "")
    return m.group(1) if m else None


def match_tab(
    tab_url: str,
    tab_title: str,
    frontmost: bool,
    rules: list[PlatformRule],
) -> MeetingMatch | None:
    """Return a MeetingMatch if the tab matches an enabled platform rule."""
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.compiled().search(tab_url or ""):
            return MeetingMatch(
                platform=rule.name,
                url=tab_url,
                title=tab_title or "",
                frontmost=frontmost,
                meeting_code=extract_meet_code(tab_url),
            )
    return None


def find_candidate(
    tabs: list[dict],
    rules: list[PlatformRule],
    require_frontmost: bool,
) -> MeetingMatch | None:
    """Pick the best meeting candidate from a list of Safari tabs.

    Each tab dict has keys: url, title, frontmost (bool).
    Preference order: a frontmost matching tab first, else the first match.
    When require_frontmost is set, only frontmost matches are eligible
    (Edge case #4 — mic used by another app while a Meet tab sits idle).
    """
    matches = []
    for tab in tabs:
        m = match_tab(
            tab.get("url", ""),
            tab.get("title", ""),
            bool(tab.get("frontmost", False)),
            rules,
        )
        if m is not None:
            matches.append(m)

    if not matches:
        return None

    frontmost_matches = [m for m in matches if m.frontmost]
    if require_frontmost:
        return frontmost_matches[0] if frontmost_matches else None
    # Prefer a frontmost match for title disambiguation (Edge case #2), else first.
    return frontmost_matches[0] if frontmost_matches else matches[0]
