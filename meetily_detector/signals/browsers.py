"""Tab enumeration across supported browsers.

Safari is the P0 platform (PRD), but Google Meet is most often used in Chrome,
so we also enumerate the Chromium family (Chrome/Brave/Edge/Chromium). Each
browser exposes tabs via its own AppleScript dictionary:

  - Safari:   `name of tab`,  `current tab of window`
  - Chromium: `title of tab`, `active tab of window`

We only query browsers that are actually running (checked with `pgrep`, which
needs no permission and never launches an app), so an unused/uninstalled
browser costs nothing and never prompts. The first query to a *running* browser
triggers that browser's one-time Automation (Apple Events) TCC prompt.
"""

from __future__ import annotations

import subprocess

from ..logutil import get_logger
from .safari import _SCRIPT as _SAFARI_SCRIPT
from .safari import parse_tabs


def _chromium_script(app: str) -> str:
    return f'''
if application "{app}" is not running then return ""
tell application "{app}"
    set _lines to {{}}
    set _frontWin to missing value
    try
        set _frontWin to front window
    end try
    repeat with w in windows
        try
            set _isFrontWin to (w is _frontWin)
            set _active to (active tab of w)
            repeat with t in (tabs of w)
                try
                    set _u to (URL of t)
                on error
                    set _u to ""
                end try
                try
                    set _n to (title of t)
                on error
                    set _n to ""
                end try
                set _isFront to (_isFrontWin and (t is _active))
                set end of _lines to ((_isFront as text) & tab & _u & tab & _n)
            end repeat
        end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    return _lines as text
end tell
'''


# (display name, macOS process name, AppleScript). Process name == app name for
# all of these, which is what `pgrep -x` matches.
_BROWSERS: list[tuple[str, str]] = [
    ("Safari", _SAFARI_SCRIPT),
    ("Google Chrome", _chromium_script("Google Chrome")),
    ("Brave Browser", _chromium_script("Brave Browser")),
    ("Microsoft Edge", _chromium_script("Microsoft Edge")),
    ("Chromium", _chromium_script("Chromium")),
    ("Arc", _chromium_script("Arc")),
]


def _is_running(process_name: str) -> bool:
    try:
        return (
            subprocess.run(
                ["pgrep", "-x", process_name], capture_output=True, timeout=3
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_osascript(script: str, timeout: float = 5.0) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")
    return proc.stdout


def running_browsers() -> list[str]:
    """Names of supported browsers currently running."""
    return [name for name, _ in _BROWSERS if _is_running(name)]


def list_all_tabs(run=_run_osascript, is_running=_is_running) -> list[dict]:
    """Enumerate meeting-relevant tabs across every running supported browser.

    Each tab dict gains a "browser" key. Returns [] off-macOS.
    """
    log = get_logger()
    tabs: list[dict] = []
    for name, script in _BROWSERS:
        if not is_running(name):
            continue
        try:
            raw = run(script)
        except FileNotFoundError:
            return []  # not macOS / osascript absent
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            # A running browser that errors is almost always a denied/pending
            # Automation grant — surface it so the user can fix it.
            log.warning(
                "%s tab enumeration failed (grant Automation -> %s under "
                "System Settings -> Privacy & Security -> Automation): %s",
                name,
                name,
                exc,
            )
            continue
        for t in parse_tabs(raw):
            t["browser"] = name
            tabs.append(t)
    return tabs
