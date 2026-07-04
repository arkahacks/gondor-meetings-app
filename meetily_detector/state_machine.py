"""Detector state machine (PRD 5.2.3).

Pure logic: it consumes per-poll signals and emits an Action. It performs no
I/O, so it is fully unit-testable off-macOS. The daemon (detector.py) is
responsible for collecting signals and executing the emitted actions.

States:
    IDLE       no meeting in view
    CANDIDATE  a Meet tab is present but the call is not confirmed joined
    RECORDING  we started an auto-recording and it is live
    COOLDOWN   we just stopped; refractory period before we may start again
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .meet import MeetingMatch


class State(enum.Enum):
    IDLE = "IDLE"
    CANDIDATE = "CANDIDATE"
    RECORDING = "RECORDING"
    COOLDOWN = "COOLDOWN"


class Action(enum.Enum):
    NONE = "NONE"
    START = "START"
    STOP = "STOP"


@dataclass(frozen=True)
class PollResult:
    action: Action
    state: State
    # Present only when action is START — the tab we should name the recording after.
    candidate: MeetingMatch | None = None
    # Human-readable reason, for logging.
    reason: str = ""


class StateMachine:
    def __init__(
        self,
        mic_debounce_polls: int = 2,
        stop_idle_polls: int = 6,
        cooldown_seconds: int = 60,
        initial_state: State = State.IDLE,
    ) -> None:
        self.mic_debounce_polls = mic_debounce_polls
        self.stop_idle_polls = stop_idle_polls
        self.cooldown_seconds = cooldown_seconds
        self.state = initial_state
        self._mic_streak = 0
        self._gone_streak = 0
        self._cooldown_until = 0.0
        # The candidate we are currently recording (for stable titles / logging).
        self.active_candidate: MeetingMatch | None = None

    def _reset_streaks(self) -> None:
        self._mic_streak = 0
        self._gone_streak = 0

    def _go(self, state: State) -> None:
        self.state = state
        self._reset_streaks()

    def poll(
        self,
        candidate: MeetingMatch | None,
        mic_active: bool,
        recording_active: bool,
        now: float,
    ) -> PollResult:
        """Advance the machine by one poll.

        Args:
            candidate: matched Meet tab this poll, or None.
            mic_active: whether the default input device is in use.
            recording_active: Meetily's actual is_recording state.
            now: current epoch seconds.
        """
        # --- Reconcile with external reality first (FR-7, FR-8, Edge case #6) ---

        # Our recording ended out from under us (laptop sleep, crash, manual
        # stop). Drop to IDLE and let normal detection restart it if the call
        # is still live on the next poll.
        if self.state is State.RECORDING and not recording_active:
            self._go(State.IDLE)
            self.active_candidate = None
            return PollResult(Action.NONE, self.state, reason="recording ended externally")

        # A recording exists that we did not start (user clicked record).
        # Stand down completely: never duplicate or interrupt it (FR-7),
        # and never auto-stop a manual recording (Edge case #3).
        if recording_active and self.state is not State.RECORDING:
            if self.state is not State.IDLE:
                self._go(State.IDLE)
            return PollResult(Action.NONE, self.state, reason="manual recording active — standing down")

        # --- Normal transitions ---
        if self.state is State.IDLE:
            return self._poll_idle(candidate, mic_active)
        if self.state is State.CANDIDATE:
            return self._poll_candidate(candidate, mic_active)
        if self.state is State.RECORDING:
            return self._poll_recording(candidate, mic_active)
        if self.state is State.COOLDOWN:
            return self._poll_cooldown(now)
        # Unreachable, but keep the machine safe.
        return PollResult(Action.NONE, self.state)

    def _poll_idle(
        self, candidate: MeetingMatch | None, mic_active: bool
    ) -> PollResult:
        if candidate is not None:
            # Enter CANDIDATE and evaluate the mic in the same poll, so a call
            # that is already joined when the tab is first seen is confirmed a
            # poll sooner (keeps join->record within the FR-1 15s budget).
            self._go(State.CANDIDATE)
            return self._poll_candidate(candidate, mic_active)
        return PollResult(Action.NONE, self.state)

    def _poll_candidate(
        self, candidate: MeetingMatch | None, mic_active: bool
    ) -> PollResult:
        if candidate is None:
            # Lobby closed / never joined — no recording (Edge case #1).
            self._go(State.IDLE)
            return PollResult(Action.NONE, self.state, reason="candidate gone before join")
        if mic_active:
            self._mic_streak += 1
            if self._mic_streak >= self.mic_debounce_polls:
                self.active_candidate = candidate
                self.state = State.RECORDING
                self._reset_streaks()
                return PollResult(
                    Action.START,
                    self.state,
                    candidate=candidate,
                    reason=f"mic active {self.mic_debounce_polls} polls — joining confirmed",
                )
            return PollResult(Action.NONE, self.state, reason="mic active, debouncing")
        # Mic not active yet — reset the debounce (still in lobby).
        self._mic_streak = 0
        return PollResult(Action.NONE, self.state, reason="candidate present, mic idle")

    def _poll_recording(
        self, candidate: MeetingMatch | None, mic_active: bool
    ) -> PollResult:
        # "Call gone" = tab closed OR mic idle. Tab-close is the dominant stop
        # signal; the streak tolerates brief mutes/reconnects (Risk table).
        call_gone = candidate is None or not mic_active
        if call_gone:
            self._gone_streak += 1
            if self._gone_streak >= self.stop_idle_polls:
                stopped = self.active_candidate
                self.state = State.COOLDOWN
                self._cooldown_until = 0.0  # set on entry below
                self._reset_streaks()
                self.active_candidate = None
                # Cooldown deadline is set relative to now by the caller-facing
                # transition; we stamp it here using the poll clock.
                return PollResult(
                    Action.STOP,
                    self.state,
                    candidate=stopped,
                    reason=f"call gone {self.stop_idle_polls} polls — stopping",
                )
            return PollResult(Action.NONE, self.state, reason="call gone, debouncing stop")
        # Call still live.
        self._gone_streak = 0
        return PollResult(Action.NONE, self.state, reason="recording")

    def _poll_cooldown(self, now: float) -> PollResult:
        if self._cooldown_until == 0.0:
            # First cooldown poll — arm the refractory timer.
            self._cooldown_until = now + self.cooldown_seconds
        if now >= self._cooldown_until:
            self._go(State.IDLE)
            self._cooldown_until = 0.0
            return PollResult(Action.NONE, self.state, reason="cooldown elapsed")
        return PollResult(Action.NONE, self.state, reason="cooldown")
