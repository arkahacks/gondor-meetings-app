"""Drive Meetily's external trigger interface (Component A).

We reuse the OS-level single-instance channel — launching the app again with
args reaches the running instance's patched `single_instance` handler
(PRD 5.1). No sockets, no HTTP, consistent with Meetily's "no unauthenticated
local API" stance.

Recording *state* is read from a small JSON status file that the patched
Meetily maintains on every start/stop. Reading a local file is not an IPC
surface; it is what lets the agent do crash reconciliation (FR-8) and tell a
manual recording apart from an auto one (FR-7, Edge case #3).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from .logutil import get_logger

DEFAULT_STATUS_FILE = "~/Library/Application Support/meetily/recording_status.json"


@dataclass(frozen=True)
class RecordingStatus:
    recording: bool
    source: str = ""  # "auto" (started by us) | "manual" (user clicked) | ""
    title: str = ""
    meeting_id: str = ""

    @property
    def is_manual(self) -> bool:
        return self.recording and self.source == "manual"

    @property
    def is_auto(self) -> bool:
        return self.recording and self.source == "auto"


class MeetilyClient:
    def __init__(
        self,
        app: str = "meetily",
        status_file: str = DEFAULT_STATUS_FILE,
        runner=subprocess.run,
    ) -> None:
        self.app = app
        self.status_file = os.path.expanduser(status_file)
        self._runner = runner
        self._log = get_logger()

    def _open_args(self, *args: str) -> None:
        cmd = ["open", "-a", self.app, "--args", *args]
        self._log.debug("meetily trigger: %s", " ".join(cmd))
        self._runner(cmd, capture_output=True, text=True, timeout=15)

    def start_recording(self, title: str) -> None:
        self._open_args("--start-recording", "--title", title)

    def stop_recording(self) -> None:
        self._open_args("--stop-recording")

    def generate_summary(self) -> None:
        self._open_args("--generate-summary")

    def status(self) -> RecordingStatus:
        """Read Meetily's recording status file. Absent/unreadable => not recording."""
        try:
            with open(self.status_file) as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return RecordingStatus(recording=False)
        return RecordingStatus(
            recording=bool(data.get("recording", False)),
            source=str(data.get("source", "")),
            title=str(data.get("title", "")),
            meeting_id=str(data.get("meeting_id", "")),
        )
