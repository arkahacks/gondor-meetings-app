"""Push a finished meeting into the Notion "Meeting Notes" database.

Matches the live DB schema: Meeting name (title), Date (datetime), Category
(multi-select: Planning / Standup / Presentation / Retro / Customer call).
Payload construction is pure and unit-tested; the network call is isolated.
"""

from __future__ import annotations

import datetime as _dt

import requests

from .logutil import get_logger

_NOTION_API = "https://api.notion.com/v1/pages"
_NOTION_VERSION = "2022-06-28"

# Notion caps a single rich_text content string at 2000 chars.
_MAX_RICH_TEXT = 1900


def infer_category(title: str, keyword_map: dict[str, str]) -> str | None:
    """First keyword (case-insensitive substring) found in the title wins."""
    low = (title or "").lower()
    for keyword, category in keyword_map.items():
        if keyword.lower() in low:
            return category
    return None


def _paragraph_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    for line in (text or "").split("\n"):
        # Chunk long lines so no rich_text exceeds Notion's limit.
        chunks = [line[i : i + _MAX_RICH_TEXT] for i in range(0, len(line), _MAX_RICH_TEXT)] or [""]
        for chunk in chunks:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": (
                            [{"type": "text", "text": {"content": chunk}}] if chunk else []
                        )
                    },
                }
            )
    # Notion rejects create calls with more than 100 children blocks.
    return blocks[:100]


def build_page_payload(
    database_id: str,
    meeting_name: str,
    when: _dt.datetime,
    category: str | None,
    summary_text: str = "",
) -> dict:
    """Build the POST /v1/pages body for a Meeting Notes row."""
    properties: dict = {
        "Meeting name": {"title": [{"text": {"content": meeting_name[:2000]}}]},
        "Date": {"date": {"start": when.isoformat()}},
    }
    if category:
        properties["Category"] = {"multi_select": [{"name": category}]}

    payload: dict = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }
    if summary_text:
        payload["children"] = _paragraph_blocks(summary_text)
    return payload


class NotionClient:
    def __init__(self, token: str, database_id: str, session=None):
        self.token = token
        self.database_id = database_id
        self._session = session or requests.Session()
        self._log = get_logger()

    def create_meeting_page(
        self,
        meeting_name: str,
        when: _dt.datetime,
        category: str | None = None,
        summary_text: str = "",
    ) -> str | None:
        """Create a Meeting Notes row. Returns the new page URL, or None on failure."""
        if not self.token or not self.database_id:
            self._log.warning("Notion sync skipped: token or database_id missing")
            return None
        payload = build_page_payload(
            self.database_id, meeting_name, when, category, summary_text
        )
        try:
            resp = self._session.post(
                _NOTION_API,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": _NOTION_VERSION,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._log.error("Notion sync failed: %s", exc)
            return None
        url = resp.json().get("url")
        self._log.info("Notion page created: %s", url)
        return url
