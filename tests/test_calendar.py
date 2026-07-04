import datetime as dt

from meetily_detector.calendar import event_meet_code, match_event_title

# Shapes mirror real Google Calendar API payloads (conferenceUrl / location /
# conferenceData.entryPoints) as returned for this account.
EVENTS = [
    {
        "summary": "Engineering Sync",
        "conferenceUrl": "https://meet.google.com/wvn-gbfk-nbb",
        "start": {"dateTime": "2026-07-10T16:00:00+01:00"},
        "end": {"dateTime": "2026-07-10T17:00:00+01:00"},
    },
    {
        "summary": "Call between Arka Serezh and Jesper Munkeby",
        "location": "https://meet.google.com/fjv-iqzy-hmx",
        "start": {"dateTime": "2026-07-06T16:15:00+01:00"},
        "end": {"dateTime": "2026-07-06T16:40:00+01:00"},
    },
    {
        "summary": "Structured conf event",
        "conferenceData": {
            "entryPoints": [{"uri": "https://meet.google.com/xyz-abcd-efg"}]
        },
        "start": {"dateTime": "2026-07-06T16:15:00+01:00"},
        "end": {"dateTime": "2026-07-06T16:40:00+01:00"},
    },
]


def test_event_meet_code_from_various_fields():
    assert event_meet_code(EVENTS[0]) == "wvn-gbfk-nbb"
    assert event_meet_code(EVENTS[1]) == "fjv-iqzy-hmx"
    assert event_meet_code(EVENTS[2]) == "xyz-abcd-efg"
    assert event_meet_code({"summary": "no link"}) is None


def test_match_event_title_hit():
    now = dt.datetime.fromisoformat("2026-07-10T16:30:00+01:00")
    assert match_event_title(EVENTS, "wvn-gbfk-nbb", now) == "Engineering Sync"


def test_match_event_title_from_location():
    now = dt.datetime.fromisoformat("2026-07-06T16:20:00+01:00")
    assert (
        match_event_title(EVENTS, "fjv-iqzy-hmx", now)
        == "Call between Arka Serezh and Jesper Munkeby"
    )


def test_match_event_title_no_match():
    now = dt.datetime.fromisoformat("2026-07-10T16:30:00+01:00")
    assert match_event_title(EVENTS, "zzz-zzzz-zzz", now) is None


def test_prefers_in_progress_event():
    # Two events share a code; the one containing `now` wins.
    events = [
        {
            "summary": "Past occurrence",
            "conferenceUrl": "https://meet.google.com/rec-urri-ngg",
            "start": {"dateTime": "2026-07-01T10:00:00+00:00"},
            "end": {"dateTime": "2026-07-01T11:00:00+00:00"},
        },
        {
            "summary": "Current occurrence",
            "conferenceUrl": "https://meet.google.com/rec-urri-ngg",
            "start": {"dateTime": "2026-07-04T15:00:00+00:00"},
            "end": {"dateTime": "2026-07-04T16:00:00+00:00"},
        },
    ]
    now = dt.datetime.fromisoformat("2026-07-04T15:30:00+00:00")
    assert match_event_title(events, "rec-urri-ngg", now) == "Current occurrence"
