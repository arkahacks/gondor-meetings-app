# Component A — Meetily fork patch (external trigger)

This is the **minimal, upstreamable** change set for Meetily that lets the
companion detector agent start/stop recording and generate summaries without a
UI click, while keeping Meetily's privacy posture (no sockets, no HTTP, no
unauthenticated local API — PRD 5.1).

It is delivered as a patch set (not applied in-tree) because the Meetily source
(`Zackriya-Solutions/meeting-minutes` fork) lives in its own repo. Apply these
against `frontend/src-tauri/` of the fork.

> **Open question #2 ("would maintainers prefer detection inside the Rust
> core?") — resolved to "whatever's easiest".** The easiest, lowest-risk path
> is what this patch does: keep *detection* in the standalone companion agent
> and add only a tiny, platform-neutral **trigger** surface to Meetily. The
> Rust diff is ~200 LoC, opt-in, and carries no macOS-specific detection code,
> so it is trivial to upstream and cheap to rebase if rejected. Porting the
> detector into the Rust core is deferred to if/when maintainers want it for
> PRO parity.

## Change set

| File | Change |
|------|--------|
| `src/external_trigger.rs` (new) | Arg parsing, guard rails, dispatch, status/summary file writing |
| `src/lib.rs` | Wire `external_trigger::handle` into the existing `single_instance` callback; register nothing new on the IPC surface |
| `migrations/2026xxxx_add_auto_record.sql` (new) | `auto_record_enabled` boolean setting, default false |
| `settings-ui.md` | One toggle in Settings → Recording |

## How the trigger works

`open -a Meetily --args --start-recording --title "…"` relaunches the app; the
OS routes the args to the already-running instance through
`tauri_plugin_single_instance` (the exact channel the project already uses to
focus the window). We parse those args and dispatch. No new IPC.

Supported args:

- `--start-recording [--title <string>]` → start via the existing
  `start_recording_with_meeting_name` path.
- `--stop-recording` → `stop_recording`.
- `--generate-summary` → `api_process_transcript` for the last meeting
  (open question #1: auto-summary on stop).
- `--recording-status` → logs current state; state is also mirrored to a status
  file the agent reads.

## Guard rails (PRD 5.1.2)

`--start-recording` is a **no-op with a logged warning + user notification** if:
- a recording is already active (never duplicate — FR-7),
- onboarding is incomplete,
- no transcription model is downloaded, or
- `auto_record_enabled` is false (external starts rejected when the toggle is
  off — FR-4).

## Visible state (Sec. 4, FR-5/FR-6)

On an externally triggered start the patch fires a `tauri_plugin_notification`
("Auto-recording started: <title> — Stop & discard?") and switches the tray
icon to the recording state. This is the non-negotiable consent affordance:
silent auto-recording is explicitly rejected.

## Status & summary files (read by the agent)

Reading a local file is not an IPC surface; it is what lets the agent do crash
reconciliation (FR-8) and tell manual vs. auto recordings apart (Edge case #3).

- `~/Library/Application Support/meetily/recording_status.json`
  `{ "recording": bool, "source": "auto"|"manual", "title": str, "meeting_id": str }`
  Written on every start/stop. `source` is `"auto"` only when started via the
  external trigger, `"manual"` when started from the UI.
- `~/Library/Application Support/meetily/last_summary.json`
  `{ "meeting_id": str, "title": str, "summary": str, "ended_at": str }`
  Written when a summary finishes, so the agent can push it to Notion.

## Upstream PR guidance (M4)

Keep the PR to `src/external_trigger.rs` + the `lib.rs` wiring + migration +
settings toggle. The detector agent is **not** part of the PR — it ships as this
companion repo, keeping the upstream diff minimal and platform-neutral.
