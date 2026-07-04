import datetime as dt

from meetily_detector.meet import MeetingMatch
from meetily_detector.title import is_generic_tab_title, resolve_title

NOW = dt.datetime(2026, 7, 4, 15, 30)


def match(title, code="wvn-gbfk-nbb"):
    return MeetingMatch(
        platform="google-meet",
        url=f"https://meet.google.com/{code}",
        title=title,
        frontmost=True,
        meeting_code=code,
    )


class FakeCal:
    def __init__(self, name):
        self.name = name

    def current_meeting_title(self, meet_code, now):
        return self.name


def test_is_generic_tab_title():
    assert is_generic_tab_title("Meet", "wvn-gbfk-nbb")
    assert is_generic_tab_title("Google Meet", "wvn-gbfk-nbb")
    assert is_generic_tab_title("Meet — wvn-gbfk-nbb", "wvn-gbfk-nbb")
    assert is_generic_tab_title("wvn-gbfk-nbb", "wvn-gbfk-nbb")
    assert is_generic_tab_title("", "wvn-gbfk-nbb")
    assert not is_generic_tab_title("Engineering Sync", "wvn-gbfk-nbb")


def test_resolve_prefers_calendar():
    title = resolve_title(
        match("Meet — wvn-gbfk-nbb"),
        NOW,
        sources=["calendar", "tab", "code"],
        calendar_lookup=FakeCal("Engineering Sync"),
        append_timestamp=True,
    )
    assert title == "Engineering Sync — 2026-07-04 15:30"


def test_falls_back_to_tab_when_no_calendar_hit():
    title = resolve_title(
        match("Weekly 1:1 - Google Meet"),
        NOW,
        sources=["calendar", "tab", "code"],
        calendar_lookup=FakeCal(None),
        append_timestamp=False,
    )
    assert title == "Weekly 1:1"


def test_falls_back_to_code_when_tab_generic():
    title = resolve_title(
        match("Meet"),
        NOW,
        sources=["calendar", "tab", "code"],
        calendar_lookup=None,
        append_timestamp=False,
    )
    assert title == "wvn-gbfk-nbb"


def test_timestamp_appended():
    title = resolve_title(
        match("Standup"),
        NOW,
        sources=["tab"],
        calendar_lookup=None,
        append_timestamp=True,
    )
    assert title == "Standup — 2026-07-04 15:30"
