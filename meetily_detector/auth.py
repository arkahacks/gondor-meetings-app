"""One-time Google Calendar OAuth consent flow (installed-app / loopback).

Produces the token file `calendar.py` reads: {access_token, refresh_token,
client_id, client_secret, expiry}. Dependency-light — uses only stdlib plus
`requests` (already a dependency), no google-auth libraries.

Run via:  meetily-detector auth-calendar
"""

from __future__ import annotations

import http.server
import json
import os
import time
import urllib.parse
import webbrowser

import requests

from .logutil import get_logger

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
_DEFAULT_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _load_client(path: str) -> dict:
    """Load a Google OAuth *Desktop app* client_secrets JSON."""
    with open(os.path.expanduser(path)) as fh:
        data = json.load(fh)
    node = data.get("installed") or data.get("web")
    if not node:
        raise ValueError(
            "client secrets JSON must contain an 'installed' or 'web' object "
            "(download a Desktop-app OAuth client from Google Cloud Console)"
        )
    return node


def build_token_record(
    body: dict, client_id: str, client_secret: str, now: float
) -> dict:
    """Shape a token endpoint response into the record calendar.py expects."""
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token", ""),
        "client_id": client_id,
        "client_secret": client_secret,
        "expiry": now + float(body.get("expires_in", 3600)),
    }


def save_token(path: str, record: dict) -> None:
    out = os.path.expanduser(path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(record, fh)
    try:
        os.chmod(out, 0o600)  # token is a secret
    except OSError:
        pass


def exchange_code(
    token_uri: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    session=None,
) -> dict:
    session = session or requests
    resp = session.post(
        token_uri,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class _CodeHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            _CodeHandler.code = params["code"][0]
            msg = "Authorization complete — you can close this tab and return to the terminal."
        elif "error" in params:
            _CodeHandler.error = params["error"][0]
            msg = f"Authorization failed: {_CodeHandler.error}"
        else:
            # Unrelated request (e.g. the browser's /favicon.ico probe) — ignore.
            msg = "Waiting for authorization…"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><p>{msg}</p></body></html>".encode())

    def log_message(self, *args):  # silence the default stderr logging
        return


def run_installed_app_flow(
    client_secrets_path: str,
    token_path: str,
    scope: str = CALENDAR_SCOPE,
    open_browser: bool = True,
    now=time.time,
) -> dict:
    """Interactive consent flow. Opens a browser, catches the redirect, saves token."""
    log = get_logger()
    client = _load_client(client_secrets_path)
    client_id = client["client_id"]
    client_secret = client["client_secret"]
    auth_uri = client.get("auth_uri", _DEFAULT_AUTH_URI)
    token_uri = client.get("token_uri", _DEFAULT_TOKEN_URI)

    _CodeHandler.code = None
    _CodeHandler.error = None
    server = http.server.HTTPServer(("127.0.0.1", 0), _CodeHandler)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"

    auth_url = auth_uri + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "access_type": "offline",  # request a refresh_token
            "prompt": "consent",
        }
    )

    print("\nAuthorize calendar access by opening this URL in your browser:\n")
    print(auth_url + "\n")
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:  # headless / no browser — the printed URL still works
            pass

    print("Waiting for you to approve in the browser…")
    while _CodeHandler.code is None and _CodeHandler.error is None:
        server.handle_request()  # tolerates favicon/other probes
    server.server_close()

    if _CodeHandler.error:
        raise RuntimeError(f"authorization failed: {_CodeHandler.error}")

    body = exchange_code(
        token_uri, _CodeHandler.code, client_id, client_secret, redirect_uri
    )
    record = build_token_record(body, client_id, client_secret, now())
    if not record["refresh_token"]:
        log.warning(
            "no refresh_token returned; re-run after revoking access at "
            "https://myaccount.google.com/permissions to force a consent screen"
        )
    save_token(token_path, record)
    return record
