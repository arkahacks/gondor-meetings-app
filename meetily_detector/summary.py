"""Read the summary Meetily writes after `--generate-summary`.

Meetily (patched) writes the finished summary to a JSON file
({meeting_id, title, summary, ended_at}); the agent waits for it to appear so
the Notion page can include the summary body (open question #1: auto-summary on
stop -> true meeting -> Notion zero-touch).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from .logutil import get_logger


@dataclass(frozen=True)
class Summary:
    meeting_id: str
    title: str
    summary: str
    ended_at: str


def read_summary(path: str) -> Summary | None:
    """Read the summary file, or None if missing/unreadable."""
    try:
        with open(os.path.expanduser(path)) as fh:
            d = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return Summary(
        meeting_id=str(d.get("meeting_id", "")),
        title=str(d.get("title", "")),
        summary=str(d.get("summary", "")),
        ended_at=str(d.get("ended_at", "")),
    )


def wait_for_summary(
    path: str,
    after_epoch: float,
    timeout: float,
    interval: float = 3.0,
    sleep=time.sleep,
    now=time.time,
    get_mtime=lambda p: os.path.getmtime(os.path.expanduser(p)),
) -> Summary | None:
    """Block until a summary newer than `after_epoch` appears, or timeout.

    Clock/sleep/mtime are injectable for testing.
    """
    deadline = now() + timeout
    while now() < deadline:
        try:
            mtime = get_mtime(path)
        except OSError:
            mtime = 0.0
        if mtime >= after_epoch:
            s = read_summary(path)
            if s is not None and s.summary:
                return s
        sleep(interval)
    get_logger().warning("summary did not appear within %ss", timeout)
    return None
