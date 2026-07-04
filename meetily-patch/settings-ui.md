# Settings UI addition (FR-4)

Add one toggle to **Settings → Recording**, bound to the `auto_record_enabled`
setting introduced by the migration.

```tsx
// frontend/src/components/settings/RecordingSettings.tsx (or equivalent)
<SettingRow
  title="Auto-detect & auto-record"
  description="Start recording automatically when a Google Meet call begins in Safari. Requires the Meetily detector agent. You remain responsible for obtaining recording consent."
>
  <Toggle
    checked={autoRecordEnabled}
    onChange={async (v) => {
      await invoke("set_setting", { key: "auto_record_enabled", value: String(v) });
      setAutoRecordEnabled(v);
    }}
  />
</SettingRow>
```

## First-run consent notice (Sec. 4, blocking requirement)

The **first** time the toggle is switched on, show a one-time modal before
persisting the value:

> **Auto-record removes the deliberate "record" click.**
> Many jurisdictions require all-party consent to record. You remain
> responsible for announcing and obtaining consent for every meeting.
> Meetily will show a notification and change the menu-bar icon whenever
> auto-recording is active, with a one-click **Stop & discard**.
>
> [ Cancel ]   [ I understand — enable ]

Persist a `auto_record_consent_ack = true` setting so the modal is shown only
once. Do not enable the feature unless the user confirms.
