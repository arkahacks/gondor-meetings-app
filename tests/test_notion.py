import datetime as dt

from meetily_detector.notion_sync import build_page_payload, infer_category

KEYWORDS = {
    "standup": "Standup",
    "sync": "Standup",
    "planning": "Planning",
    "retro": "Retro",
    "customer": "Customer call",
}


def test_infer_category():
    assert infer_category("Engineering Sync — 2026-07-04", KEYWORDS) == "Standup"
    assert infer_category("Q3 Planning", KEYWORDS) == "Planning"
    assert infer_category("Sprint Retro", KEYWORDS) == "Retro"
    assert infer_category("Customer call: Acme", KEYWORDS) == "Customer call"
    assert infer_category("Random chat", KEYWORDS) is None


def test_build_page_payload_shape():
    when = dt.datetime(2026, 7, 4, 15, 30, tzinfo=dt.timezone.utc)
    payload = build_page_payload(
        "db-123", "Engineering Sync", when, "Standup", "Line one\nLine two"
    )
    assert payload["parent"] == {"database_id": "db-123"}
    props = payload["properties"]
    assert props["Meeting name"]["title"][0]["text"]["content"] == "Engineering Sync"
    assert props["Date"]["date"]["start"] == "2026-07-04T15:30:00+00:00"
    assert props["Category"]["multi_select"] == [{"name": "Standup"}]
    # Two body lines -> two paragraph blocks.
    assert len(payload["children"]) == 2
    assert (
        payload["children"][0]["paragraph"]["rich_text"][0]["text"]["content"]
        == "Line one"
    )


def test_build_page_payload_no_category_no_body():
    when = dt.datetime(2026, 7, 4, 15, 30, tzinfo=dt.timezone.utc)
    payload = build_page_payload("db-123", "Untitled", when, None, "")
    assert "Category" not in payload["properties"]
    assert "children" not in payload


def test_long_body_chunked_and_capped():
    when = dt.datetime(2026, 7, 4, 15, 30, tzinfo=dt.timezone.utc)
    huge = "x" * 5000  # one long line -> chunked into multiple blocks
    payload = build_page_payload("db-123", "Big", when, None, huge)
    assert all(
        len(b["paragraph"]["rich_text"][0]["text"]["content"]) <= 1900
        for b in payload["children"]
    )
    assert len(payload["children"]) <= 100
