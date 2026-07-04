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
    set _lines to {}
    try
        set _front to front window
    on error
        set _front to missing value
    end try
    repeat with w in windows
        try
            set _isFrontWin to (w is _front)
            set _activeTab to (current tab of w)
            repeat with t in (tabs of w)
                try
                    set _u to (URL of t)
                on error
                    set _u to ""
                end try
                try
                    set _n to (name of t)
                on error
                    set _n to ""
                end try
                set _isFront to (_isFrontWin and (t is _activeTab))
                set end of _lines to ((_isFront as text) & tab & _u & tab & _n)
            end try
        end try
    end repeat
    set AppleScript's text item delimiters to (ASCII character 10)
    return _lines as text
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
