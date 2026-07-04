"""CLI entrypoint for the Meetily auto-detect companion agent."""

from __future__ import annotations

import argparse
import sys
import time

from . import config as configmod
from .detector import Detector
from .logutil import setup_logging


def _build_logger(cfg: configmod.Config):
    return setup_logging(
        cfg.logging.file,
        level=cfg.logging.level,
        max_bytes=cfg.logging.max_bytes,
        backup_count=cfg.logging.backup_count,
        redact_meeting_code=cfg.logging.redact_meeting_code,
    )


def cmd_run(args) -> int:
    cfg = configmod.load(args.config)
    _build_logger(cfg)
    Detector(cfg, dry_run=args.dry_run).run()
    return 0


def cmd_snooze(args) -> int:
    deadline = configmod.snooze_until(args.hours, time.time())
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(deadline))
    print(f"Auto-record snoozed until {when}.")
    return 0


def cmd_unsnooze(args) -> int:
    configmod.clear_snooze()
    print("Auto-record snooze cleared.")
    return 0


def cmd_auth_calendar(args) -> int:
    cfg = configmod.load(args.config)
    _build_logger(cfg)
    from .auth import run_installed_app_flow

    secrets = args.client_secrets or cfg.calendar.oauth_client_secrets
    token_file = args.token_file or cfg.calendar.token_file
    run_installed_app_flow(secrets, token_file, open_browser=not args.no_browser)
    print(f"\nCalendar token saved to {token_file}")
    print("Titles will now be enriched from your Google Calendar.")
    return 0


def cmd_status(args) -> int:
    cfg = configmod.load(args.config)
    _build_logger(cfg)
    det = Detector(cfg)
    st = det.meetily.status()
    snoozed = configmod.is_snoozed(time.time())
    print(f"agent enabled : {cfg.enabled}")
    print(f"snoozed       : {snoozed}")
    print(f"recording     : {st.recording} (source={st.source or 'n/a'})")
    if st.recording:
        print(f"current title : {st.title}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meetily-detector", description=__doc__)
    p.add_argument("--config", help="path to config.toml", default=None)
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the detector daemon (foreground)")
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="detect and log what would happen, but never trigger Meetily or Notion",
    )
    run_p.set_defaults(func=cmd_run)

    sp = sub.add_parser("snooze", help="pause auto-record for N hours")
    sp.add_argument("hours", type=float)
    sp.set_defaults(func=cmd_snooze)

    sub.add_parser("unsnooze", help="clear an active snooze").set_defaults(
        func=cmd_unsnooze
    )

    ap = sub.add_parser(
        "auth-calendar",
        help="run the one-time Google Calendar OAuth consent flow and save the token",
    )
    ap.add_argument("--client-secrets", help="path to the Desktop-app client_secrets JSON")
    ap.add_argument("--token-file", help="where to write the token (default: config value)")
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    ap.set_defaults(func=cmd_auth_calendar)
    sub.add_parser("status", help="print agent + recording status").set_defaults(
        func=cmd_status
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
