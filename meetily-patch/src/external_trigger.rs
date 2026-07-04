//! External trigger handling for auto-record (Component A, PRD 5.1).
//!
//! Parses args delivered through the single-instance channel and dispatches to
//! the *existing* recording/summary command paths. No new IPC surface: this is
//! reached only via `open -a Meetily --args …`, which the OS routes to the
//! running instance through `tauri_plugin_single_instance`.
//!
//! NOTE FOR THE FORK: the three `crate::commands::…` calls below must bind to
//! Meetily's actual internal functions (the same ones the Tauri commands
//! `start_recording_with_meeting_name`, `stop_recording`, `api_process_transcript`
//! wrap). Names are as documented in the project; confirm signatures on apply.

use std::fs;
use std::path::PathBuf;

use serde_json::json;
use tauri::{AppHandle, Manager};

/// Parsed external trigger.
#[derive(Debug, PartialEq)]
pub enum Trigger {
    Start { title: Option<String> },
    Stop,
    GenerateSummary,
    Status,
    None,
}

/// Pure arg parser — unit-testable without a running app.
pub fn parse_args(args: &[String]) -> Trigger {
    let mut iter = args.iter().peekable();
    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--start-recording" => {
                let mut title = None;
                if let Some(next) = iter.peek() {
                    if next.as_str() == "--title" {
                        iter.next();
                        title = iter.next().cloned();
                    }
                }
                return Trigger::Start { title };
            }
            "--stop-recording" => return Trigger::Stop,
            "--generate-summary" => return Trigger::GenerateSummary,
            "--recording-status" => return Trigger::Status,
            _ => {}
        }
    }
    Trigger::None
}

fn app_support_dir() -> PathBuf {
    // ~/Library/Application Support/meetily
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home).join("Library/Application Support/meetily")
}

/// Mirror recording state to the status file the companion agent reads.
pub fn write_status(recording: bool, source: &str, title: &str, meeting_id: &str) {
    let dir = app_support_dir();
    let _ = fs::create_dir_all(&dir);
    let body = json!({
        "recording": recording,
        "source": source,          // "auto" for external trigger, "manual" for UI
        "title": title,
        "meeting_id": meeting_id,
    });
    let _ = fs::write(dir.join("recording_status.json"), body.to_string());
}

/// Reason a start was refused, for the notification/log (PRD 5.1.2).
enum Refusal {
    AutoRecordDisabled,
    AlreadyRecording,
    OnboardingIncomplete,
    NoModel,
}

impl Refusal {
    fn message(&self) -> &'static str {
        match self {
            Refusal::AutoRecordDisabled => "Auto-record is off — enable it in Settings.",
            Refusal::AlreadyRecording => "A recording is already in progress.",
            Refusal::OnboardingIncomplete => "Finish Meetily onboarding first.",
            Refusal::NoModel => "No transcription model downloaded.",
        }
    }
}

/// Evaluate guard rails. Returns `Err(Refusal)` if the start must be rejected.
fn check_guards(app: &AppHandle) -> Result<(), Refusal> {
    if !crate::settings::auto_record_enabled(app) {
        return Err(Refusal::AutoRecordDisabled);
    }
    if crate::commands::is_recording(app) {
        return Err(Refusal::AlreadyRecording);
    }
    if !crate::onboarding::is_complete(app) {
        return Err(Refusal::OnboardingIncomplete);
    }
    if !crate::models::has_downloaded_model(app) {
        return Err(Refusal::NoModel);
    }
    Ok(())
}

/// Entry point wired into the single-instance callback in `lib.rs`.
pub fn handle(app: &AppHandle, args: &[String]) {
    match parse_args(args) {
        Trigger::Start { title } => handle_start(app, title),
        Trigger::Stop => handle_stop(app),
        Trigger::GenerateSummary => handle_summary(app),
        Trigger::Status => log_status(app),
        Trigger::None => {
            // Ordinary second-launch with no trigger args: preserve existing
            // behaviour — just focus the window.
            crate::tray::focus_main_window(app);
        }
    }
}

fn handle_start(app: &AppHandle, title: Option<String>) {
    if let Err(refusal) = check_guards(app) {
        log::warn!("auto-start rejected: {}", refusal.message());
        notify(app, "Auto-record not started", refusal.message());
        return;
    }
    let title = title.unwrap_or_else(|| "Meeting".to_string());
    log::info!("external auto-start: {}", title);

    // Reuse the existing UI code path.
    match crate::commands::start_recording_with_meeting_name(app, title.clone()) {
        Ok(meeting_id) => {
            write_status(true, "auto", &title, &meeting_id);
            crate::tray::set_recording(app, true);
            notify(
                app,
                "Auto-recording started",
                &format!("{title} — tap to Stop & discard"),
            );
        }
        Err(e) => {
            log::error!("start_recording failed: {e}");
            notify(app, "Auto-record failed to start", &e.to_string());
        }
    }
}

fn handle_stop(app: &AppHandle) {
    // Never auto-stop a *manual* recording (Edge case #3): only stop if our
    // status file says the active recording is ours.
    if current_source(app).as_deref() != Some("auto") {
        log::info!("stop trigger ignored: active recording is not auto");
        return;
    }
    let _ = crate::commands::stop_recording(app);
    crate::tray::set_recording(app, false);
    write_status(false, "", "", "");
    log::info!("external auto-stop complete");
}

fn handle_summary(app: &AppHandle) {
    log::info!("external summary generation requested");
    // Runs the same summary path the UI uses; on completion Meetily should
    // write last_summary.json (see below).
    std::thread::spawn({
        let app = app.clone();
        move || match crate::commands::api_process_transcript_last(&app) {
            Ok(s) => write_summary(&s.meeting_id, &s.title, &s.summary),
            Err(e) => log::error!("summary generation failed: {e}"),
        }
    });
}

fn write_summary(meeting_id: &str, title: &str, summary: &str) {
    let dir = app_support_dir();
    let _ = fs::create_dir_all(&dir);
    let body = json!({
        "meeting_id": meeting_id,
        "title": title,
        "summary": summary,
        "ended_at": chrono::Utc::now().to_rfc3339(),
    });
    let _ = fs::write(dir.join("last_summary.json"), body.to_string());
}

fn log_status(app: &AppHandle) {
    let rec = crate::commands::is_recording(app);
    log::info!("recording-status: {rec}");
}

fn current_source(_app: &AppHandle) -> Option<String> {
    let path = app_support_dir().join("recording_status.json");
    let data = fs::read_to_string(path).ok()?;
    let v: serde_json::Value = serde_json::from_str(&data).ok()?;
    v.get("source").and_then(|s| s.as_str()).map(String::from)
}

fn notify(app: &AppHandle, title: &str, body: &str) {
    use tauri_plugin_notification::NotificationExt;
    let _ = app.notification().builder().title(title).body(body).show();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn parses_start_with_title() {
        assert_eq!(
            parse_args(&s(&["--start-recording", "--title", "Standup — 2026-07-04"])),
            Trigger::Start { title: Some("Standup — 2026-07-04".into()) }
        );
    }

    #[test]
    fn parses_start_without_title() {
        assert_eq!(
            parse_args(&s(&["--start-recording"])),
            Trigger::Start { title: None }
        );
    }

    #[test]
    fn parses_stop_and_summary_and_status() {
        assert_eq!(parse_args(&s(&["--stop-recording"])), Trigger::Stop);
        assert_eq!(parse_args(&s(&["--generate-summary"])), Trigger::GenerateSummary);
        assert_eq!(parse_args(&s(&["--recording-status"])), Trigger::Status);
    }

    #[test]
    fn no_trigger_args() {
        assert_eq!(parse_args(&s(&["/path/to/app", "--other"])), Trigger::None);
    }
}
