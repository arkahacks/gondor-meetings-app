-- Add the auto-record opt-in toggle (PRD 5.1.3, FR-4).
-- Default false: the feature is strictly opt-in. When false, external
-- --start-recording triggers are rejected by the guard rails in
-- external_trigger.rs.
--
-- Follows the existing settings-table migration style; adjust the table/column
-- names if the fork's `settings` schema differs.

INSERT OR IGNORE INTO settings (key, value)
VALUES ('auto_record_enabled', 'false');
