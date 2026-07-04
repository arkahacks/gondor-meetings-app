"""Configuration loading, defaults, and mutable runtime state (snooze)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace

try:  # stdlib on 3.11+, backport on 3.10
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    import tomli as tomllib  # type: ignore

from .meet import PlatformRule

DEFAULT_CONFIG_PATH = "~/.config/meetily-detector/config.toml"
DEFAULT_SNOOZE_PATH = "~/.config/meetily-detector/snooze.json"


@dataclass(frozen=True)
class DetectionConfig:
    mic_debounce_polls: int = 2
    stop_idle_polls: int = 6
    cooldown_seconds: int = 60
    require_frontmost_tab: bool = True


@dataclass(frozen=True)
class TitleConfig:
    sources: tuple[str, ...] = ("calendar", "tab", "code")
    append_timestamp: bool = True


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool = True
    oauth_client_secrets: str = "~/.config/meetily-detector/gcal_client.json"
    token_file: str = "~/.config/meetily-detector/gcal_token.json"
    window_minutes: int = 30


@dataclass(frozen=True)
class SummaryConfig:
    auto_generate: bool = True
    wait_timeout_seconds: int = 600
    output_file: str = "~/Library/Application Support/meetily/last_summary.json"


@dataclass(frozen=True)
class NotionConfig:
    enabled: bool = True
    token: str = ""
    database_id: str = ""
    category_keywords: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LoggingConfig:
    file: str = "~/Library/Logs/meetily-detector/detector.log"
    level: str = "INFO"
    max_bytes: int = 1_048_576
    backup_count: int = 3
    redact_meeting_code: bool = False


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    poll_interval_seconds: int = 5
    meetily_app: str = "meetily"
    meetily_status_file: str = "~/Library/Application Support/meetily/recording_status.json"
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    platforms: tuple[PlatformRule, ...] = ()
    title: TitleConfig = field(default_factory=TitleConfig)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)
    summary: SummaryConfig = field(default_factory=SummaryConfig)
    notion: NotionConfig = field(default_factory=NotionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def enabled_rules(self) -> list[PlatformRule]:
        return [r for r in self.platforms if r.enabled]


_DEFAULT_RULES = (
    PlatformRule(
        name="google-meet",
        enabled=True,
        url_regex=r"^https://meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})(\?.*)?$",
    ),
)


def _rules_from(raw: dict) -> tuple[PlatformRule, ...]:
    platforms = raw.get("platforms", {})
    rules = platforms.get("rule", [])
    if not rules:
        return _DEFAULT_RULES
    return tuple(
        PlatformRule(
            name=r["name"],
            enabled=bool(r.get("enabled", True)),
            url_regex=r["url_regex"],
        )
        for r in rules
    )


def from_dict(raw: dict) -> Config:
    """Build a Config from a parsed TOML dict, applying defaults for anything absent."""
    general = raw.get("general", {})
    det = raw.get("detection", {})
    title = raw.get("title", {})
    cal = raw.get("calendar", {})
    summ = raw.get("summary", {})
    notion = raw.get("notion", {})
    log = raw.get("logging", {})

    return Config(
        enabled=bool(general.get("enabled", True)),
        poll_interval_seconds=int(general.get("poll_interval_seconds", 5)),
        meetily_app=str(general.get("meetily_app", "meetily")),
        meetily_status_file=str(
            general.get("meetily_status_file", Config.meetily_status_file)
        ),
        detection=DetectionConfig(
            mic_debounce_polls=int(det.get("mic_debounce_polls", 2)),
            stop_idle_polls=int(det.get("stop_idle_polls", 6)),
            cooldown_seconds=int(det.get("cooldown_seconds", 60)),
            require_frontmost_tab=bool(det.get("require_frontmost_tab", True)),
        ),
        platforms=_rules_from(raw),
        title=TitleConfig(
            sources=tuple(title.get("sources", ["calendar", "tab", "code"])),
            append_timestamp=bool(title.get("append_timestamp", True)),
        ),
        calendar=CalendarConfig(
            enabled=bool(cal.get("enabled", True)),
            oauth_client_secrets=str(
                cal.get("oauth_client_secrets", CalendarConfig.oauth_client_secrets)
            ),
            token_file=str(cal.get("token_file", CalendarConfig.token_file)),
            window_minutes=int(cal.get("window_minutes", 30)),
        ),
        summary=SummaryConfig(
            auto_generate=bool(summ.get("auto_generate", True)),
            wait_timeout_seconds=int(summ.get("wait_timeout_seconds", 600)),
            output_file=str(summ.get("output_file", SummaryConfig.output_file)),
        ),
        notion=NotionConfig(
            enabled=bool(notion.get("enabled", True)),
            # Env var wins over the file so the token need not be written to disk.
            token=os.environ.get("NOTION_TOKEN", str(notion.get("token", ""))),
            database_id=str(notion.get("database_id", "")),
            category_keywords=dict(notion.get("category_keywords", {})),
        ),
        logging=LoggingConfig(
            file=str(log.get("file", LoggingConfig.file)),
            level=str(log.get("level", "INFO")),
            max_bytes=int(log.get("max_bytes", 1_048_576)),
            backup_count=int(log.get("backup_count", 3)),
            redact_meeting_code=bool(log.get("redact_meeting_code", False)),
        ),
    )


def load(path: str | None = None) -> Config:
    """Load config from disk. Missing file => all defaults."""
    resolved = os.path.expanduser(path or DEFAULT_CONFIG_PATH)
    if not os.path.exists(resolved):
        return replace(Config(), platforms=_DEFAULT_RULES)
    with open(resolved, "rb") as fh:
        raw = tomllib.load(fh)
    return from_dict(raw)


# --- Snooze state (FR-10): "snooze auto-record for N hours" -----------------


def snooze_until(hours: float, now: float, path: str | None = None) -> float:
    """Write a snooze deadline `hours` from `now`; return the deadline epoch."""
    resolved = os.path.expanduser(path or DEFAULT_SNOOZE_PATH)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    deadline = now + hours * 3600.0
    with open(resolved, "w") as fh:
        json.dump({"until": deadline}, fh)
    return deadline


def is_snoozed(now: float, path: str | None = None) -> bool:
    """True if a snooze deadline is set and still in the future."""
    resolved = os.path.expanduser(path or DEFAULT_SNOOZE_PATH)
    if not os.path.exists(resolved):
        return False
    try:
        with open(resolved) as fh:
            deadline = float(json.load(fh).get("until", 0))
    except (ValueError, OSError, json.JSONDecodeError):
        return False
    return now < deadline


def clear_snooze(path: str | None = None) -> None:
    resolved = os.path.expanduser(path or DEFAULT_SNOOZE_PATH)
    try:
        os.remove(resolved)
    except FileNotFoundError:
        pass
