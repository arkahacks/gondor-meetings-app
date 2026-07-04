from meetily_detector import config as configmod
from meetily_detector.detector import Detector
from meetily_detector.meetily import RecordingStatus
from meetily_detector.state_machine import State

MEET_TAB = {
    "url": "https://meet.google.com/abc-defg-hij",
    "title": "Engineering Sync",
    "frontmost": True,
}


class FakeMeetily:
    def __init__(self):
        self._recording = False
        self._source = ""
        self._title = ""
        self.started = []
        self.stopped = 0
        self.summaries = 0

    def start_recording(self, title):
        self._recording, self._source, self._title = True, "auto", title
        self.started.append(title)

    def stop_recording(self):
        self._recording, self._source = False, ""
        self.stopped += 1

    def generate_summary(self):
        self.summaries += 1

    def status(self):
        return RecordingStatus(self._recording, self._source, self._title, "")


class FakeNotion:
    def __init__(self):
        self.pages = []

    def create_meeting_page(self, meeting_name, when, category=None, summary_text=""):
        self.pages.append({"name": meeting_name, "category": category})
        return "https://notion/page"


def make_cfg():
    return configmod.from_dict(
        {
            "detection": {"mic_debounce_polls": 2, "stop_idle_polls": 2, "cooldown_seconds": 60},
            "calendar": {"enabled": False},
            "summary": {"auto_generate": False},
            "notion": {
                "enabled": True,
                "token": "t",
                "database_id": "db",
                "category_keywords": {"sync": "Standup"},
            },
        }
    )


def test_full_auto_cycle_to_notion():
    clock = {"t": 0.0}
    tabs = {"list": [MEET_TAB]}
    mic = {"on": True}
    meetily = FakeMeetily()
    notion = FakeNotion()

    det = Detector(
        make_cfg(),
        meetily=meetily,
        notion=notion,
        list_tabs=lambda: list(tabs["list"]),
        mic_in_use=lambda: mic["on"],
        clock=lambda: clock["t"],
        sleep=lambda _s: None,
    )

    def poll(t):
        clock["t"] = t
        det.poll_once()

    poll(0)   # CANDIDATE
    assert det.sm.state is State.CANDIDATE
    poll(5)   # mic debounce 1
    poll(10)  # START
    assert det.sm.state is State.RECORDING
    assert len(meetily.started) == 1
    assert meetily.started[0].startswith("Engineering Sync")

    poll(12)  # recording (within grace)
    assert det.sm.state is State.RECORDING

    # Call ends: tab closes, mic off, grace expired.
    tabs["list"] = []
    mic["on"] = False
    poll(30)  # gone 1
    poll(35)  # gone 2 -> STOP
    assert meetily.stopped == 1

    # Post-stop pipeline runs in a thread; wait for it.
    det._post_stop_thread.join(timeout=5)
    assert len(notion.pages) == 1
    assert notion.pages[0]["name"].startswith("Engineering Sync")
    assert notion.pages[0]["category"] == "Standup"


def test_manual_recording_makes_detector_stand_down():
    clock = {"t": 0.0}
    meetily = FakeMeetily()
    # Simulate a manual recording already in progress.
    meetily._recording, meetily._source = True, "manual"

    det = Detector(
        make_cfg(),
        meetily=meetily,
        notion=FakeNotion(),
        list_tabs=lambda: [MEET_TAB],
        mic_in_use=lambda: True,
        clock=lambda: clock["t"],
        sleep=lambda _s: None,
    )
    for t in range(0, 40, 5):
        clock["t"] = t
        det.poll_once()
    # Never started an auto recording, never stopped the manual one.
    assert meetily.started == []
    assert meetily.stopped == 0
    assert det.sm.state is State.IDLE


def test_dry_run_never_triggers_meetily_or_notion():
    clock = {"t": 0.0}
    tabs = {"list": [MEET_TAB]}
    mic = {"on": True}
    meetily = FakeMeetily()
    notion = FakeNotion()

    det = Detector(
        make_cfg(),
        meetily=meetily,
        notion=notion,
        list_tabs=lambda: list(tabs["list"]),
        mic_in_use=lambda: mic["on"],
        clock=lambda: clock["t"],
        sleep=lambda _s: None,
        dry_run=True,
    )

    def poll(t):
        clock["t"] = t
        det.poll_once()

    poll(0)   # CANDIDATE
    poll(5)   # would START (dry-run) -> RECORDING
    assert det.sm.state is State.RECORDING
    poll(30)  # still recording (intent authoritative in dry-run)
    assert det.sm.state is State.RECORDING
    tabs["list"] = []
    mic["on"] = False
    poll(35)  # gone 1
    poll(40)  # gone 2 -> would STOP
    assert det.sm.state is State.COOLDOWN
    # Nothing real was ever invoked.
    assert meetily.started == [] and meetily.stopped == 0
    assert notion.pages == []


def test_boot_reconciliation_stops_orphan():
    meetily = FakeMeetily()
    meetily._recording, meetily._source = True, "auto"  # orphan from a crash

    det = Detector(
        make_cfg(),
        meetily=meetily,
        notion=FakeNotion(),
        list_tabs=lambda: [],   # no Meet tab -> orphan
        mic_in_use=lambda: False,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
    )
    det.reconcile_on_boot()
    assert meetily.stopped == 1
