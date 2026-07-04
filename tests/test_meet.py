from meetily_detector.config import _DEFAULT_RULES
from meetily_detector.meet import extract_meet_code, find_candidate, match_tab

RULES = list(_DEFAULT_RULES)


def test_extract_meet_code():
    assert extract_meet_code("https://meet.google.com/abc-defg-hij") == "abc-defg-hij"
    assert extract_meet_code("https://meet.google.com/abc-defg-hij?authuser=0") == "abc-defg-hij"
    assert extract_meet_code("https://meet.google.com/new") is None
    assert extract_meet_code("https://meet.google.com/") is None
    assert extract_meet_code("https://example.com") is None


def test_match_tab_google_meet():
    m = match_tab("https://meet.google.com/wvn-gbfk-nbb", "Engineering Sync", True, RULES)
    assert m is not None
    assert m.platform == "google-meet"
    assert m.meeting_code == "wvn-gbfk-nbb"
    assert m.frontmost is True


def test_match_tab_landing_page_excluded():
    assert match_tab("https://meet.google.com/", "Meet", True, RULES) is None
    assert match_tab("https://meet.google.com/new", "Meet", True, RULES) is None


def test_find_candidate_prefers_frontmost():
    tabs = [
        {"url": "https://meet.google.com/aaa-bbbb-ccc", "title": "Back", "frontmost": False},
        {"url": "https://meet.google.com/ddd-eeee-fff", "title": "Front", "frontmost": True},
    ]
    m = find_candidate(tabs, RULES, require_frontmost=False)
    assert m.title == "Front"


def test_find_candidate_require_frontmost_rejects_background():
    tabs = [
        {"url": "https://meet.google.com/aaa-bbbb-ccc", "title": "Back", "frontmost": False},
        {"url": "https://mail.google.com", "title": "Mail", "frontmost": True},
    ]
    assert find_candidate(tabs, RULES, require_frontmost=True) is None
    # Without the gate, the background Meet tab is eligible.
    assert find_candidate(tabs, RULES, require_frontmost=False) is not None


def test_find_candidate_none_when_no_meet():
    tabs = [{"url": "https://news.ycombinator.com", "title": "HN", "frontmost": True}]
    assert find_candidate(tabs, RULES, require_frontmost=True) is None
