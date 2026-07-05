# Meetily Auto-Detect & Auto-Record

Zero-touch meeting capture for [Meetily](https://github.com/Zackriya-Solutions/meeting-minutes)
(Community Edition). When a Google Meet call starts in Safari on your Mac, this
starts a Meetily recording within ~10–15s without a click, names it from your
calendar, stops it when the call ends, generates the summary, and files the
meeting into a Notion database — all locally, no browser extension, no new
network service.

This repo implements the PRD *"Auto-Detect & Auto-Record for Meetily"* and is
the **companion detector agent** (PRD Component B). The small, upstreamable
Meetily-side patch (Component A) lives in [`meetily-patch/`](meetily-patch/).

> ⚠️ **Consent notice (please read).** Auto-record removes the deliberate act
> of clicking "record." Many jurisdictions require all-party consent to record
> a conversation. **You remain responsible for announcing and obtaining consent
> for every meeting.** The feature is opt-in (default off), always shows a
> macOS notification and a menu-bar recording indicator when active, and offers
> one-click **Stop & discard**. Silent auto-recording is explicitly not a
> supported mode.

## How it works

```
┌────────────────────────────┐      trigger        ┌──────────────────────────┐
│  Detector agent (launchd)  │ ──────────────────▶ │  Meetily (Tauri app)     │
│  - Safari tab poll (AS)    │  open -a --args     │  - patched arg handler   │
│  - CoreAudio mic-in-use    │                     │  - start/stop/summary    │
│  - state machine           │ ◀────────────────── │  - tray + notification   │
└────────────────────────────┘   status file       └──────────────────────────┘
        │
        ├── Google Calendar (read-only) → meeting title
        └── Notion API → "Meeting Notes" database
```

Every 5s the agent:
1. **Tab signal (primary):** enumerates Safari tabs (AppleScript) and matches
   `meet.google.com/xxx-xxxx-xxx` (the landing page and `/new` are excluded).
2. **Mic signal (confirmation):** checks whether the default input device is in
   use (CoreAudio). A Meet tab can sit in the lobby forever; mic activation is
   the reliable "actually joined" signal. **Both** must hold to start.
3. Runs a **state machine** (`IDLE → CANDIDATE → RECORDING → COOLDOWN`) with
   debounce so brief blips don't start/stop recordings.

On start it resolves a title, triggers Meetily, and Meetily shows the
notification + tray change. On stop it triggers summary generation, waits for
the summary, and files the meeting into Notion.

### Title comes from your calendar

Meet tab titles are often generic ("Meet — abc-defg-hij"). The agent takes the
meeting **code** from the tab URL, finds the Google Calendar event that owns
that conference link, and uses the event's name (e.g. *"Engineering Sync"*).
Order is configurable (`calendar → tab → code`); calendar needs only the
read-only scope. Tab title is the fallback when there's no matching event.

## PRD requirement coverage

| FR | Where |
|----|-------|
| FR-1 detect within 15s | `meet.py`, `state_machine.py` (2-poll join in ~10s) |
| FR-2 title `"<name> — YYYY-MM-DD HH:MM"` | `title.py`, `calendar.py` |
| FR-3 auto-stop within 60s | `state_machine.py` (`stop_idle_polls`) |
| FR-4 opt-in toggle, reject when off | `meetily-patch/` (`auto_record_enabled`) |
| FR-5 notification + stop&discard | `meetily-patch/src/external_trigger.rs` |
| FR-6 tray reflects state | `meetily-patch/src/external_trigger.rs` |
| FR-7 never touch a manual recording | `state_machine.py` (stand-down), status `source` |
| FR-8 crash reconciliation | `detector.reconcile_on_boot` |
| FR-9 per-domain allowlist | `config.toml [platforms]` |
| FR-10 snooze N hours | `meetily-detector snooze <h>` |
| FR-11 rotating local log, no telemetry | `logutil.py` |

Edge cases (lobby-never-joined, back-to-back calls, manual-before-join, mic
used by another app, Safari closed, sleep mid-call, model missing) are handled
in the state machine and detector; see tests in `tests/`.

## Install

Requires macOS 14+ and Python 3.10+.

```bash
git clone <this-repo> && cd gondor-meetings-app
pip install -e .

mkdir -p ~/.config/meetily-detector
cp config.example.toml ~/.config/meetily-detector/config.toml
$EDITOR ~/.config/meetily-detector/config.toml   # set notion token, calendar, etc.
```

**1. Apply the Meetily patch** (Component A) — see [`meetily-patch/README.md`](meetily-patch/README.md).
Then enable the toggle in **Meetily → Settings → Recording**.

**2. Calendar (optional, for good titles).** In Google Cloud Console create an
OAuth **Desktop app** client with the `calendar.readonly` scope, download its
`client_secret*.json`, and save it to
`~/.config/meetily-detector/gcal_client.json`. Then run the built-in consent
flow — it opens a browser, catches the redirect on a loopback port, and writes
the token file for you:

```bash
meetily-detector auth-calendar
```

If calendar is disabled or unauthenticated, titles fall back to the tab title.

**3. Notion (optional).** Create an internal integration, share the
"Meeting Notes" database with it, and set `NOTION_TOKEN` (or `[notion].token`).
The `database_id` default already points at the target DB.

**4. Run under launchd:**
```bash
cp launchd/com.gondor.meetily-detector.plist ~/Library/LaunchAgents/
# edit ProgramArguments if your python path differs
launchctl load ~/Library/LaunchAgents/com.gondor.meetily-detector.plist
```
The first Safari enumeration triggers a one-time **Automation → Safari** prompt
(scoped to Safari only; no Accessibility or Screen Recording).

## CLI

```bash
meetily-detector run           # run in the foreground (launchd runs this)
meetily-detector run --dry-run # detect & log what WOULD happen; never triggers
                               # Meetily or Notion — safe to try before patching Meetily
meetily-detector status        # agent + recording status
meetily-detector auth-calendar # one-time Google Calendar OAuth consent flow
meetily-detector snooze 2      # pause auto-record for 2 hours
meetily-detector unsnooze
```

## Privacy

Tab URLs and titles are processed in memory and appear only in the local
rotating log (with an optional meeting-code redaction flag). The only network
calls are to Google Calendar (read-only, your account) and Notion (your DB) —
both of which you can disable. Nothing else leaves the machine.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Pure logic (state machine, URL matching, title resolution, calendar matching,
Notion payloads, config, summary waiting) is fully covered and runs on any
platform. The macOS signal collectors (Safari/CoreAudio) are thin and injected
for testing.

## Scope note

Google Meet on macOS. Tab detection works across **Safari, Chrome, Brave, Edge,
and Chromium** (only browsers that are actually running are queried; each needs
its own one-time Automation grant). Firefox/Arc, Zoom/Teams native, and calendar
pre-arming are future work (the `[platforms]` allowlist already lets you add
web-based Zoom/Teams by config). Bot-style joining is explicitly out of scope —
this is a local capture tool for meetings you attend.
