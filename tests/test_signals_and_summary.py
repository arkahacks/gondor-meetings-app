import json

from meetily_detector.meetily import MeetilyClient, RecordingStatus
from meetily_detector.signals.safari import parse_tabs
from meetily_detector.summary import read_summary, wait_for_summary


def test_parse_tabs():
    raw = (
        "true\thttps://meet.google.com/abc-defg-hij\tEngineering Sync\n"
        "false\thttps://mail.google.com\tInbox\n"
        "\n"  # blank line ignored
    )
    tabs = parse_tabs(raw)
    assert len(tabs) == 2
    assert tabs[0] == {
        "url": "https://meet.google.com/abc-defg-hij",
        "title": "Engineering Sync",
        "frontmost": True,
    }
    assert tabs[1]["frontmost"] is False


def test_parse_tabs_title_with_tab_char():
    raw = "true\thttps://x\tHas\ttab\tin\ttitle"
    tabs = parse_tabs(raw)
    assert tabs[0]["title"] == "Has\ttab\tin\ttitle"


def test_meetily_status_reads_file(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"recording": True, "source": "auto", "title": "T", "meeting_id": "m1"}))
    client = MeetilyClient(status_file=str(p))
    st = client.status()
    assert st == RecordingStatus(recording=True, source="auto", title="T", meeting_id="m1")
    assert st.is_auto and not st.is_manual


def test_meetily_status_missing_file_is_not_recording(tmp_path):
    client = MeetilyClient(status_file=str(tmp_path / "absent.json"))
    assert client.status().recording is False


def test_meetily_start_stop_invokes_open():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)

    client = MeetilyClient(app="meetily", runner=fake_run)
    client.start_recording("Standup — 2026-07-04 15:30")
    client.stop_recording()
    assert calls[0][:4] == ["open", "-a", "meetily", "--args"]
    assert "--start-recording" in calls[0] and "--title" in calls[0]
    assert "--stop-recording" in calls[1]


def test_read_summary(tmp_path):
    p = tmp_path / "sum.json"
    p.write_text(json.dumps({"meeting_id": "m1", "title": "T", "summary": "S", "ended_at": "now"}))
    s = read_summary(str(p))
    assert s.summary == "S" and s.title == "T"


def test_wait_for_summary_succeeds_with_injected_clock(tmp_path):
    p = tmp_path / "sum.json"
    p.write_text(json.dumps({"meeting_id": "m1", "title": "T", "summary": "done", "ended_at": "x"}))

    ticks = iter([0.0, 1.0, 2.0, 3.0])
    s = wait_for_summary(
        str(p),
        after_epoch=-1,
        timeout=10,
        interval=0,
        sleep=lambda _: None,
        now=lambda: next(ticks),
        get_mtime=lambda _p: 5.0,
    )
    assert s is not None and s.summary == "done"


def test_wait_for_summary_times_out(tmp_path):
    ticks = iter([0.0, 5.0, 11.0])
    s = wait_for_summary(
        str(tmp_path / "missing.json"),
        after_epoch=0,
        timeout=10,
        interval=0,
        sleep=lambda _: None,
        now=lambda: next(ticks),
        get_mtime=lambda _p: 0.0,
    )
    assert s is None
