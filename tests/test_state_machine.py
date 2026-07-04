from meetily_detector.meet import MeetingMatch
from meetily_detector.state_machine import Action, State, StateMachine


def cand(code="abc-defg-hij", frontmost=True):
    return MeetingMatch(
        platform="google-meet",
        url=f"https://meet.google.com/{code}",
        title="Standup",
        frontmost=frontmost,
        meeting_code=code,
    )


def test_full_lifecycle_start_and_stop():
    sm = StateMachine(mic_debounce_polls=2, stop_idle_polls=3, cooldown_seconds=60)

    # Tab appears -> CANDIDATE, no action.
    r = sm.poll(cand(), mic_active=False, recording_active=False, now=0)
    assert r.state is State.CANDIDATE and r.action is Action.NONE

    # Mic active 1 poll -> still debouncing.
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=5)
    assert r.action is Action.NONE and r.state is State.CANDIDATE

    # Mic active 2nd poll -> START.
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=10)
    assert r.action is Action.START and r.state is State.RECORDING
    assert r.candidate.meeting_code == "abc-defg-hij"

    # Recording confirmed by Meetily; call live -> no action.
    r = sm.poll(cand(), mic_active=True, recording_active=True, now=15)
    assert r.action is Action.NONE and r.state is State.RECORDING

    # Tab closes; needs 3 gone polls to stop.
    r = sm.poll(None, mic_active=False, recording_active=True, now=20)
    assert r.action is Action.NONE
    r = sm.poll(None, mic_active=False, recording_active=True, now=25)
    assert r.action is Action.NONE
    r = sm.poll(None, mic_active=False, recording_active=True, now=30)
    assert r.action is Action.STOP and r.state is State.COOLDOWN


def test_mic_blip_resets_debounce():
    sm = StateMachine(mic_debounce_polls=2)
    sm.poll(cand(), mic_active=False, recording_active=False, now=0)  # CANDIDATE
    sm.poll(cand(), mic_active=True, recording_active=False, now=5)   # streak 1
    r = sm.poll(cand(), mic_active=False, recording_active=False, now=10)  # blip resets
    assert r.action is Action.NONE and r.state is State.CANDIDATE
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=15)  # streak 1 again
    assert r.action is Action.NONE


def test_lobby_never_joined_no_recording():
    sm = StateMachine(mic_debounce_polls=2)
    sm.poll(cand(), mic_active=False, recording_active=False, now=0)  # CANDIDATE
    # Tab closes while still in lobby (mic never came on).
    r = sm.poll(None, mic_active=False, recording_active=False, now=5)
    assert r.state is State.IDLE and r.action is Action.NONE


def test_brief_mute_tolerated():
    sm = StateMachine(mic_debounce_polls=1, stop_idle_polls=3)
    sm.poll(cand(), mic_active=True, recording_active=False, now=0)  # START
    # Mic idle for 2 polls (brief mute) then back — must not stop.
    assert sm.poll(cand(), False, True, 5).action is Action.NONE
    assert sm.poll(cand(), False, True, 10).action is Action.NONE
    r = sm.poll(cand(), True, True, 15)  # un-muted, streak resets
    assert r.action is Action.NONE and r.state is State.RECORDING


def test_manual_recording_stand_down():
    sm = StateMachine(mic_debounce_polls=1)
    # A manual recording is already active; a Meet tab + mic present.
    r = sm.poll(cand(), mic_active=True, recording_active=True, now=0)
    assert r.action is Action.NONE
    assert r.state is State.IDLE  # stood down, never started


def test_manual_recording_never_auto_stopped():
    sm = StateMachine()
    # Manual recording active, no tab -> we still never emit STOP.
    for t in range(0, 60, 5):
        r = sm.poll(None, mic_active=False, recording_active=True, now=t)
        assert r.action is Action.NONE


def test_recording_ended_externally_resets():
    sm = StateMachine(mic_debounce_polls=1)
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=0)  # START -> RECORDING
    assert r.action is Action.START
    # Meetily is now recording; laptop sleeps and recording stops under us.
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=5)
    assert r.state is State.IDLE and r.action is Action.NONE
    # Call still live -> re-detect and restart on the next poll.
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=10)
    assert r.action is Action.START


def test_cooldown_refractory():
    sm = StateMachine(mic_debounce_polls=1, stop_idle_polls=1, cooldown_seconds=60)
    sm.poll(cand(), mic_active=True, recording_active=False, now=0)  # START
    r = sm.poll(None, mic_active=False, recording_active=True, now=5)  # STOP
    assert r.action is Action.STOP and r.state is State.COOLDOWN

    # Within cooldown, even a live call does not restart.
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=10)
    assert r.state is State.COOLDOWN and r.action is Action.NONE

    # After the refractory window, back to IDLE, then can start again.
    r = sm.poll(cand(), mic_active=True, recording_active=False, now=80)
    assert r.state is State.IDLE
