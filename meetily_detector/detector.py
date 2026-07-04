"""The detector daemon: collect signals every poll, drive the state machine,
execute its actions against Meetily, and run the post-stop summary -> Notion
pipeline. Wires the pure pieces (state machine, title, config) to the platform
signals and network clients.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time

from . import config as configmod
from .calendar import GoogleCalendarClient
from .logutil import get_logger
from .meet import find_candidate
from .meetily import MeetilyClient
from .notion_sync import NotionClient, infer_category
from .signals import mic as micmod
from .signals import safari as safarimod
from .state_machine import Action, State, StateMachine
from .summary import wait_for_summary
from .title import resolve_title

# After issuing a start/stop, trust our own expectation of Meetily's recording
# state for this many seconds, since `open -a --args` reaches the app
# asynchronously and the status file can briefly lag reality.
_GRACE_SECONDS = 15.0


class Detector:
    def __init__(
        self,
        cfg: configmod.Config,
        meetily: MeetilyClient | None = None,
        calendar: GoogleCalendarClient | None = None,
        notion: NotionClient | None = None,
        list_tabs=safarimod.list_tabs,
        mic_in_use=micmod.mic_in_use,
        clock=time.time,
        sleep=time.sleep,
        dry_run: bool = False,
    ) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.log = get_logger()
        self.meetily = meetily or MeetilyClient(
            app=cfg.meetily_app, status_file=cfg.meetily_status_file
        )
        self.calendar = calendar
        if self.calendar is None and cfg.calendar.enabled:
            self.calendar = GoogleCalendarClient(
                cfg.calendar.token_file, cfg.calendar.window_minutes
            )
        self.notion = notion
        if self.notion is None and cfg.notion.enabled:
            self.notion = NotionClient(cfg.notion.token, cfg.notion.database_id)

        self._list_tabs = list_tabs
        self._mic_in_use = mic_in_use
        self._clock = clock
        self._sleep = sleep

        self.sm = StateMachine(
            mic_debounce_polls=cfg.detection.mic_debounce_polls,
            stop_idle_polls=cfg.detection.stop_idle_polls,
            cooldown_seconds=cfg.detection.cooldown_seconds,
        )
        self._grace_until = 0.0
        self._expected_recording = False
        self._active_title = ""
        self._active_started_at: _dt.datetime | None = None
        self._running = False

    # --- signal collection -------------------------------------------------

    def _now_dt(self) -> _dt.datetime:
        return _dt.datetime.fromtimestamp(self._clock()).astimezone()

    def _recording_active(self, status_recording: bool, now: float) -> bool:
        # In dry-run there is no real recording, so our intent is authoritative;
        # this lets the full start->record->stop cycle be demonstrated from the
        # tab/mic signals alone, without a patched Meetily.
        if self.dry_run:
            return self._expected_recording
        if now < self._grace_until:
            return self._expected_recording
        return status_recording

    def _mic_active(self) -> bool:
        # Unknown (None, e.g. CoreAudio unavailable) is treated as not-active so
        # we never trigger without a positive join signal.
        return self._mic_in_use() is True

    # --- boot reconciliation (FR-8) ---------------------------------------

    def reconcile_on_boot(self) -> None:
        status = self.meetily.status()
        tabs = self._list_tabs()
        candidate = find_candidate(
            tabs, self.cfg.enabled_rules(), self.cfg.detection.require_frontmost_tab
        )
        if status.is_auto and candidate is None:
            # Orphaned auto-recording after a detector crash (PRD 5.2.4).
            self.log.warning("orphaned auto-recording found on boot; stopping")
            if not self.dry_run:
                self.meetily.stop_recording()
        elif status.is_auto and candidate is not None:
            # Our recording is legitimately still live — adopt it.
            self.log.info("adopting in-progress auto-recording on boot")
            self.sm.state = State.RECORDING
            self.sm.active_candidate = candidate
            self._active_title = status.title
            self._active_started_at = self._now_dt()
        elif status.is_manual:
            self.log.info("manual recording active on boot; standing down")

    # --- one poll ----------------------------------------------------------

    def poll_once(self) -> None:
        now = self._clock()

        if not self.cfg.enabled:
            return
        # Snooze (FR-10) prevents new starts but never interrupts a live one.
        snoozed = configmod.is_snoozed(now)

        status = self.meetily.status()
        recording_active = self._recording_active(status.recording, now)

        tabs = self._list_tabs()
        candidate = find_candidate(
            tabs, self.cfg.enabled_rules(), self.cfg.detection.require_frontmost_tab
        )

        # When snoozed and not already recording, hide candidates so the machine
        # cannot advance toward a start.
        if snoozed and self.sm.state in (State.IDLE, State.CANDIDATE):
            candidate = None

        result = self.sm.poll(candidate, self._mic_active(), recording_active, now)

        if result.reason:
            self.log.debug("state=%s action=%s (%s)", result.state.value, result.action.value, result.reason)

        if result.action is Action.START:
            self._do_start(result.candidate)
        elif result.action is Action.STOP:
            self._do_stop()

    def _do_start(self, candidate) -> None:
        now_dt = self._now_dt()
        title = resolve_title(
            candidate,
            now_dt,
            self.cfg.title.sources,
            self.calendar if self.cfg.calendar.enabled else None,
            self.cfg.title.append_timestamp,
        )
        if self.dry_run:
            self.log.info("[dry-run] would auto-start recording: %s", title)
        else:
            self.log.info("auto-start recording: %s", title)
            self.meetily.start_recording(title)
        self._active_title = title
        self._active_started_at = now_dt
        self._expected_recording = True
        self._grace_until = self._clock() + _GRACE_SECONDS

    def _do_stop(self) -> None:
        self._expected_recording = False
        self._grace_until = self._clock() + _GRACE_SECONDS
        if self.dry_run:
            self.log.info(
                "[dry-run] would auto-stop, generate summary, and file to Notion: %s",
                self._active_title,
            )
            return
        self.log.info("auto-stop recording: %s", self._active_title)
        self.meetily.stop_recording()
        # Run the summary -> Notion pipeline off the poll loop so detection
        # keeps running while the (potentially minutes-long) summary generates.
        title = self._active_title
        started = self._active_started_at or self._now_dt()
        t = threading.Thread(target=self._post_stop, args=(title, started), daemon=True)
        t.start()
        self._post_stop_thread = t  # retained for tests / graceful shutdown

    # --- post-stop pipeline (summary + Notion) -----------------------------

    def _post_stop(self, title: str, started_at: _dt.datetime) -> None:
        summary_text = ""
        if self.cfg.summary.auto_generate:
            self.log.info("triggering summary generation")
            self.meetily.generate_summary()
            s = wait_for_summary(
                self.cfg.summary.output_file,
                after_epoch=self._clock() - 5,
                timeout=self.cfg.summary.wait_timeout_seconds,
            )
            if s is not None:
                summary_text = s.summary
                if s.title:
                    title = s.title

        if self.notion is not None and self.cfg.notion.enabled:
            category = infer_category(title, self.cfg.notion.category_keywords)
            self.notion.create_meeting_page(
                meeting_name=title,
                when=started_at,
                category=category,
                summary_text=summary_text,
            )

    # --- run loop ----------------------------------------------------------

    def run(self) -> None:
        self.log.info("meetily-detector starting (poll=%ss)", self.cfg.poll_interval_seconds)
        self.reconcile_on_boot()
        self._running = True
        while self._running:
            try:
                self.poll_once()
            except Exception:  # never let one bad poll kill the daemon
                self.log.exception("poll failed")
            self._sleep(self.cfg.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
