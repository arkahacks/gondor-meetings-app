"""Google Calendar title enrichment.

Answers the "pull the current meeting from gmeet" question: the Meet code from
the Safari tab is matched against the calendar event that owns that conference
link, and the event's human name (e.g. "Engineering Sync") is used as the
recording title instead of the generic "Meet — abc-defg-hij".

Only the read-only Calendar scope is needed. The matching logic is pure and
unit-tested against real event payloads; network access is isolated in
GoogleCalendarClient and fails soft (returns None -> caller falls back to the
tab title).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass

import requests

from .logutil import get_logger
from .meet import extract_meet_code

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def event_meet_code(event: dict) -> str | None:
    """Extract a Meet code from any conference-bearing field of an event."""
    for field in ("conferenceUrl", "hangoutLink", "location"):
        code = extract_meet_code(str(event.get(field, "")))
        if code:
            return code
    # Structured conferenceData.entryPoints[].uri
    entry_points = (event.get("conferenceData", {}) or {}).get("entryPoints", []) or []
    for ep in entry_points:
        code = extract_meet_code(str(ep.get("uri", "")))
        if code:
            return code
    # Last resort: the description often embeds the meet URL.
    return extract_meet_code(str(event.get("description", "")))


def _event_start_end(event: dict) -> tuple[_dt.datetime | None, _dt.datetime | None]:
    def parse(node: dict) -> _dt.datetime | None:
        if not node:
            return None
        raw = node.get("dateTime") or node.get("date")
        if not raw:
            return None
        try:
            if "T" not in raw:  # all-day date
                d = _dt.date.fromisoformat(raw)
                return _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc)
            return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    return parse(event.get("start", {})), parse(event.get("end", {}))


def match_event_title(events: list[dict], meet_code: str, now: _dt.datetime) -> str | None:
    """Return the summary of the event owning `meet_code`, or None.

    When several events share the code (recurring series), prefer the one whose
    time window contains `now`; otherwise the one starting nearest to `now`.
    """
    candidates = [e for e in events if event_meet_code(e) == meet_code]
    if not candidates:
        return None

    def score(event: dict) -> tuple[int, float]:
        start, end = _event_start_end(event)
        if start and end and start <= now <= end:
            return (0, 0.0)  # currently in progress — best
        if start:
            return (1, abs((start - now).total_seconds()))
        return (2, float("inf"))

    best = min(candidates, key=score)
    summary = str(best.get("summary", "")).strip()
    return summary or None


@dataclass
class _Token:
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    expiry: float  # epoch seconds


class GoogleCalendarClient:
    """Minimal read-only Calendar client using a stored OAuth token.

    The token file is the standard installed-app credential JSON produced by a
    one-time consent flow (see README): access_token, refresh_token, client_id,
    client_secret, expiry.
    """

    def __init__(self, token_file: str, window_minutes: int = 30, session=None):
        self.token_file = os.path.expanduser(token_file)
        self.window_minutes = window_minutes
        self._session = session or requests.Session()
        self._log = get_logger()

    def _load_token(self) -> _Token | None:
        try:
            with open(self.token_file) as fh:
                d = json.load(fh)
            return _Token(
                access_token=d.get("access_token", ""),
                refresh_token=d.get("refresh_token", ""),
                client_id=d.get("client_id", ""),
                client_secret=d.get("client_secret", ""),
                expiry=float(d.get("expiry", 0)),
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._log.warning("calendar token unreadable: %s", exc)
            return None

    def _save_token(self, tok: _Token) -> None:
        with open(self.token_file, "w") as fh:
            json.dump(
                {
                    "access_token": tok.access_token,
                    "refresh_token": tok.refresh_token,
                    "client_id": tok.client_id,
                    "client_secret": tok.client_secret,
                    "expiry": tok.expiry,
                },
                fh,
            )

    def _ensure_fresh(self, tok: _Token, now: float) -> _Token | None:
        if tok.access_token and now < tok.expiry - 60:
            return tok
        if not tok.refresh_token:
            return tok if tok.access_token else None
        resp = self._session.post(
            _TOKEN_URL,
            data={
                "client_id": tok.client_id,
                "client_secret": tok.client_secret,
                "refresh_token": tok.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        tok.access_token = body["access_token"]
        tok.expiry = now + float(body.get("expires_in", 3600))
        self._save_token(tok)
        return tok

    def current_meeting_title(self, meet_code: str, now: _dt.datetime) -> str | None:
        """Return the calendar name for the given Meet code, or None on any failure."""
        try:
            tok = self._load_token()
            if tok is None:
                return None
            tok = self._ensure_fresh(tok, now.timestamp())
            if tok is None or not tok.access_token:
                return None
            window = _dt.timedelta(minutes=self.window_minutes)
            resp = self._session.get(
                _EVENTS_URL,
                headers={"Authorization": f"Bearer {tok.access_token}"},
                params={
                    "timeMin": (now - window).isoformat(),
                    "timeMax": (now + window).isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 50,
                },
                timeout=10,
            )
            resp.raise_for_status()
            events = resp.json().get("items", [])
            return match_event_title(events, meet_code, now)
        except (requests.RequestException, KeyError, ValueError) as exc:
            self._log.warning("calendar lookup failed for %s: %s", meet_code, exc)
            return None
