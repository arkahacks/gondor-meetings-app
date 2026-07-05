"""Safari tab enumeration via AppleScript (Apple Events / Automation).

Primary detection signal (PRD 5.2.1). Requires the one-time Automation
(Apple Events -> Safari) TCC grant, scoped to Safari only (Sec. 7).

Returns a list of tab dicts: {"url": str, "title": str, "frontmost": bool}.
`frontmost` is true only for the active tab of the frontmost Safari window,
which the frontmost-tab gate (Edge case #4) relies on.

When Safari is not running the agent idles at near-zero cost (Edge case #5):
this returns [] without spawning AppleScript work.
"""

from __future__ import annotations

import subprocess

from ..logutil import get_logger

# Emits one line per tab: "<frontmost>\t<url>\t<title>". Guarded so a window
# with no tabs, or no front window, degrades to an empty result rather than
# an AppleScript error.
_SCRIPT = r'''
if application "Safari" is not running then return ""
tell application "Safari"
    set _out to ""
    set _front to missing value
    try
        set _front to window 1
    end try
    repeat with w in windows
        set _ct to missing value
        try
            set _ct to current tab of w
        end try
        try
            repeat with t in (tabs of w)
                set _u to (URL of t)
                if _u is missing value then set _u to ""
                set _n to (name of t)
                if _n is missing value then set _n to ""
                set _f to "false"
                if (_ct is not missing value) and (t is _ct) and (w is _front) then set _f to "true"
                set _out to _out & _f & tab & _u & tab & _n & linefeed
            end repeat
        end try
    end repeat
    return _out
end tell
'''


def _run_osascript(script: str, timeout: float = 5.0) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")
    return proc.stdout


def parse_tabs(raw: str) -> list[dict]:
    """Parse osascript output into tab dicts. Pure — unit-tested off-macOS."""
    tabs: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        frontmost_str, url, title = parts[0], parts[1], "\t".join(parts[2:])
        tabs.append(
            {
                "url": url,
                "title": title,
                "frontmost": frontmost_str.strip().lower() == "true",
            }
        )
    return tabs


def list_tabs(run=_run_osascript) -> list[dict]:
    """Enumerate open Safari tabs. Returns [] if Safari is closed or on error.

    `run` is injectable for testing.
    """
    try:
        raw = run(_SCRIPT)
    except FileNotFoundError:
        # Not on macOS / osascript absent.
        get_logger().debug("osascript unavailable; no Safari tab signal")
        return []
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        get_logger().warning("Safari tab enumeration failed: %s", exc)
        return []
    return parse_tabs(raw)
